"""Financial-data regression checks. Run with Python's built-in unittest."""
import csv
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from income_tracker import (Ledger, Filters, ValidationError, MAX_CENTS, parse_amount,
                            parse_date, decimal_amount, period_bounds, totals, export_csv)


def record(**overrides):
    item = dict(date="2026-10-20", kind="Income", description="Freelance work",
                category="Freelance", amount_cents=12345, currency="USD",
                account="USD bank", reference="INV-0007", notes="Received in full.")
    item.update(overrides)
    return item


class AmountAndDateTests(unittest.TestCase):
    def test_decimal_and_comma_amounts_stay_exact(self):
        for text, expected in (("0.01", 1), ("0.10", 10), ("0.20", 20),
                               ("1234,56", 123456), (" 12.5 ", 1250), ("42", 4200)):
            with self.subTest(text=text):
                self.assertEqual(parse_amount(text), expected)
        self.assertEqual(parse_amount("0.10") + parse_amount("0.20"), 30)
        self.assertEqual(parse_amount(decimal_amount(MAX_CENTS)), MAX_CENTS)

    def test_ambiguous_or_invalid_amounts_are_rejected(self):
        for text in ("", "0", "0.00", "-1", "+1", "1e3", "NaN", "Infinity", "1.005",
                     "1,234", "1,234.56", "1.234,56", "12 345", "$5", "1.", "1,", "9" * 200):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError):
                    parse_amount(text)
        with self.assertRaises(ValidationError):
            parse_amount(decimal_amount(MAX_CENTS + 1))

    def test_strict_dates_and_calendar_edges(self):
        self.assertEqual(parse_date("2024-02-29"), "2024-02-29")
        for text in ("2026-02-29", "2026-13-01", "2026-1-1", "20/10/2026", "20261020"):
            with self.subTest(text=text):
                with self.assertRaises(ValidationError):
                    parse_date(text)
        self.assertEqual(period_bounds("Last month", date(2026, 1, 1)), ("2025-12-01", "2025-12-31"))
        self.assertEqual(period_bounds("This month", date(2024, 2, 1)), ("2024-02-01", "2024-02-29"))


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.path = self.root / "my ledger.sqlite3"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.ledger.close()
        self.folder.cleanup()

    def test_create_edit_close_and_reopen_preserves_full_record(self):
        row_id = self.ledger.save(record(description="Türkçe iş — ödeme", notes="First line\nİkinci satır"))
        first = self.ledger.get(row_id)
        self.assertEqual(first["reference"], "INV-0007")
        replacement = dict(first, amount_cents=98765, description="Corrected payment")
        self.assertEqual(self.ledger.save(replacement, row_id), row_id)
        self.ledger.close()
        self.ledger = Ledger(self.path)
        saved = self.ledger.get(row_id)
        self.assertEqual(saved["amount_cents"], 98765)
        self.assertEqual(saved["notes"], "First line\nİkinci satır")
        self.assertEqual(saved["created_at"], first["created_at"])
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 1)

    def test_currencies_never_mix_and_small_amounts_sum_exactly(self):
        self.ledger.save(record(amount_cents=10))
        self.ledger.save(record(amount_cents=20))
        self.ledger.save(record(kind="Expense", amount_cents=7))
        self.ledger.save(record(currency="TRY", amount_cents=900000))
        usd = self.ledger.query(Filters("USD"))
        self.assertEqual(totals(usd), (30, 7, 23))
        self.assertEqual(totals(self.ledger.query(Filters("TRY"))), (900000, 0, 900000))
        with self.assertRaises(ValidationError):
            totals(usd + self.ledger.query(Filters("TRY")))

    def test_date_boundaries_and_filters_are_inclusive(self):
        self.ledger.save(record(date="2026-09-30", amount_cents=100))
        self.ledger.save(record(date="2026-10-01", amount_cents=200))
        self.ledger.save(record(date="2026-10-31", kind="Expense", amount_cents=300, account="Cash"))
        self.ledger.save(record(date="2026-11-01", amount_cents=400))
        rows = self.ledger.query(Filters("USD", "2026-10-01", "2026-10-31"))
        self.assertEqual(totals(rows), (200, 300, -100))
        self.assertEqual(len(self.ledger.query(Filters("USD", kind="Expense", account="Cash"))), 1)
        self.assertEqual(self.ledger.query(Filters("USD", kind="Income", account="Cash")), [])
        with self.assertRaises(ValidationError):
            self.ledger.query(Filters("USD", "2026-10-31", "2026-10-01"))

    def test_search_treats_wildcards_and_sql_as_literal_text(self):
        unusual = "100%_complete'; DROP TABLE transactions;--"
        self.ledger.save(record(description=unusual, notes="A searchable NOTE", reference="000009"))
        self.ledger.save(record(description="Unrelated", notes="", reference=""))
        for term in ("100%_", "DROP TABLE", "searchable note", "000009"):
            with self.subTest(term=term):
                self.assertEqual(len(self.ledger.query(Filters("USD", search=term))), 1)
        self.assertEqual(len(self.ledger.query(Filters("USD", search="%_missing"))), 0)
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 2)

    def test_invalid_edit_is_atomic(self):
        row_id = self.ledger.save(record())
        for change in (dict(amount_cents=0), dict(amount_cents=True), dict(amount_cents=1.5),
                       dict(amount_cents=MAX_CENTS + 1), dict(currency="BTC"), dict(description=""),
                       dict(date="2026-02-30"), dict(notes="n" * 3001)):
            with self.subTest(change=change):
                with self.assertRaises(ValidationError):
                    self.ledger.save(record(**change), row_id)
                self.assertEqual(self.ledger.get(row_id)["amount_cents"], 12345)
        with self.assertRaises(ValidationError):
            self.ledger.save(record(), 999999)
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 1)

    def test_delete_and_undo_restore_the_exact_original(self):
        row_id = self.ledger.save(record())
        original = self.ledger.get(row_id)
        removed = self.ledger.delete(row_id)
        self.assertEqual(self.ledger.query(Filters("USD")), [])
        new_id = self.ledger.save(record(description="Later payment"))
        self.assertNotEqual(new_id, row_id)
        self.ledger.undo_delete(removed)
        self.assertEqual(self.ledger.get(row_id), original)

    def test_backup_restore_covers_all_currencies_and_keeps_safety_copy(self):
        self.ledger.save(record(currency="USD"))
        self.ledger.save(record(currency="TRY", amount_cents=50000))
        backup = self.root / "backups elsewhere" / "export #1.sqlite3"
        self.ledger.backup(backup)
        self.ledger.save(record(currency="EUR"))
        safety = self.ledger.restore(backup)
        self.assertTrue(safety.is_file())
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 1)
        self.assertEqual(len(self.ledger.query(Filters("TRY"))), 1)
        self.assertEqual(self.ledger.query(Filters("EUR")), [])
        with closing(sqlite3.connect(safety)) as old:
            self.assertEqual(old.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 3)
        # The active connection remains usable after restore.
        self.ledger.save(record(currency="CHF"))
        self.assertEqual(len(self.ledger.query(Filters("CHF"))), 1)

    def test_invalid_backups_leave_active_data_unchanged(self):
        row_id = self.ledger.save(record())
        broken = self.root / "not-a-database.sqlite3"
        broken.write_text("This is not SQLite.", encoding="utf-8")
        unrelated = self.root / "different.sqlite3"
        with closing(sqlite3.connect(unrelated)) as db, db:
            db.execute("CREATE TABLE unrelated (value TEXT)")
        for candidate in (broken, unrelated, self.root / "missing.sqlite3", self.path):
            with self.subTest(candidate=candidate.name):
                with self.assertRaises(ValidationError):
                    self.ledger.restore(candidate)
                self.assertEqual(self.ledger.get(row_id)["description"], "Freelance work")
        self.assertFalse((self.root / "missing.sqlite3").exists())

    def test_backup_cannot_overwrite_active_ledger(self):
        self.ledger.save(record())
        with self.assertRaises(ValidationError):
            self.ledger.backup(self.path)
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 1)

    def test_daily_snapshot_is_full_and_does_not_overwrite_first_snapshot(self):
        self.assertIsNone(self.ledger.auto_backup())
        self.ledger.save(record())
        snapshot = self.ledger.auto_backup()
        self.ledger.save(record(currency="TRY"))
        self.assertEqual(self.ledger.auto_backup(), snapshot)
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 1)
        self.assertEqual(len(self.ledger.query(Filters("TRY"))), 1)

    def test_csv_preserves_amounts_unicode_notes_and_blocks_formulas(self):
        self.ledger.save(record(description='=HYPERLINK("bad")', category="Türkçe, kategori",
                                reference="000007", notes="One line\nSecond, line", account="@account"))
        path = self.root / "transactions.csv"
        export_csv(path, self.ledger.query(Filters("USD")))
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["Amount"], "123.45")
        self.assertEqual(rows[0]["Currency"], "USD")
        self.assertEqual(rows[0]["Category"], "Türkçe, kategori")
        self.assertEqual(rows[0]["Reference"], "000007")
        self.assertEqual(rows[0]["Notes"], "One line\nSecond, line")
        self.assertEqual(rows[0]["Description"], "'=HYPERLINK(\"bad\")")
        self.assertEqual(rows[0]["Account"], "'@account")

    def test_backup_files_can_be_moved_after_validation_and_restore(self):
        self.ledger.save(record())
        backup = self.root / "backup.sqlite3"
        moved = self.root / "moved.sqlite3"
        self.ledger.backup(backup)
        backup.replace(moved)
        self.ledger.validate_backup(moved)
        moved.replace(backup)
        self.ledger.restore(backup)
        backup.replace(moved)
        self.assertTrue(moved.is_file())
        self.assertEqual(len(self.ledger.query(Filters("USD"))), 1)

    def test_existing_unrelated_database_is_not_adopted(self):
        path = self.root / "unrelated.sqlite3"
        with closing(sqlite3.connect(path)) as other, other:
            other.execute("CREATE TABLE documents (body TEXT)")
            other.execute("INSERT INTO documents VALUES ('keep me')")
        with self.assertRaises(ValidationError):
            Ledger(path)
        with closing(sqlite3.connect(path)) as other:
            self.assertEqual(other.execute("SELECT body FROM documents").fetchone()[0], "keep me")


if __name__ == "__main__":
    unittest.main()
