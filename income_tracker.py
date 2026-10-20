#!/usr/bin/env python3
"""LedgerDesk: an offline income and expense tracker. Python 3.10+, no pip packages."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

APP_NAME = "LedgerDesk"
VERSION = "1.1.0"
SCHEMA_VERSION = 1
CURRENCIES = ("TRY", "USD", "EUR", "GBP", "CAD", "CHF")
MAX_CENTS = 99_999_999_999_999
CATEGORIES = {
    "Income": ("Freelance", "Salary", "Business income", "Refund", "Other income"),
    "Expense": ("Food & groceries", "Housing", "Transport", "Bills & utilities",
                "Health", "Subscriptions", "Shopping", "Business", "Travel", "Other expenses"),
}
FIELDS = ("date", "kind", "description", "category", "amount_cents", "currency",
          "account", "reference", "notes")


class ValidationError(ValueError):
    """A readable, actionable validation error."""


def default_data_file() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / APP_NAME / "ledger.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError("Use dates in YYYY-MM-DD format, for example 2026-10-20.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError("Enter a real calendar date in YYYY-MM-DD format.") from exc
    return value


def parse_amount(value: str) -> int:
    """Positive amounts with at most two decimals; no ambiguous group separators."""
    value = value.strip()
    if not re.fullmatch(r"\d+(?:[.,]\d{1,2})?", value):
        raise ValidationError("Enter a positive amount, such as 1250.50 or 1250,50.\n"
                              "Leave out currency symbols and thousands separators.")
    try:
        amount = Decimal(value.replace(",", "."))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValidationError("Enter a valid amount with at most two decimal places.") from exc
    if amount > Decimal(MAX_CENTS) / 100:
        raise ValidationError("This amount is too large. Enter less than 1 trillion.")
    cents = int(amount * 100)
    if cents <= 0:
        raise ValidationError("The amount must be greater than zero.")
    return cents


def decimal_amount(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole}.{fraction:02d}"


def money(cents: int, currency: str = "") -> str:
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{currency + ' ' if currency else ''}{sign}{whole:,}.{fraction:02d}"


def shift_month(day: date, offset: int) -> date:
    absolute = day.year * 12 + day.month - 1 + offset
    year, month = divmod(absolute, 12)
    return date(year, month + 1, 1)


def period_bounds(period: str, today: date | None = None) -> tuple[str, str]:
    today = today or date.today()
    if period == "This month":
        return today.replace(day=1).isoformat(), (shift_month(today, 1) - timedelta(days=1)).isoformat()
    if period == "Last month":
        return shift_month(today, -1).isoformat(), (today.replace(day=1) - timedelta(days=1)).isoformat()
    if period == "This year":
        return date(today.year, 1, 1).isoformat(), date(today.year, 12, 31).isoformat()
    return "", ""


class Filters(NamedTuple):
    currency: str = "TRY"
    start: str = ""
    end: str = ""
    kind: str = "All types"
    account: str = "All accounts"
    search: str = ""


def validate_record(record: dict) -> dict:
    clean = {}
    clean["date"] = parse_date(str(record.get("date", "")))
    for key, limit in (("description", 180), ("category", 80), ("account", 80),
                       ("reference", 180), ("notes", 3000)):
        clean[key] = str(record.get(key, "")).strip()
        if key in ("description", "category", "account") and not clean[key]:
            raise ValidationError(f"Enter a {key}.")
        if len(clean[key]) > limit:
            raise ValidationError(f"Keep {key} to {limit} characters or fewer.")
        if "\x00" in clean[key]:
            raise ValidationError(f"Remove the null character from {key}.")
    clean["kind"] = record.get("kind", "")
    if clean["kind"] not in CATEGORIES:
        raise ValidationError("Choose Income or Expense.")
    clean["currency"] = record.get("currency", "")
    if clean["currency"] not in CURRENCIES:
        raise ValidationError("Choose a supported currency.")
    amount = record.get("amount_cents")
    if type(amount) is not int or not 0 < amount <= MAX_CENTS:
        raise ValidationError("The amount must be a positive number with at most two decimal places.")
    clean["amount_cents"] = amount
    return clean


def csv_text(value: str) -> str:
    """Prevent spreadsheet programs from evaluating user-entered text as a formula."""
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def export_csv(path: Path, rows: list[dict]) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Date", "Type", "Description", "Category", "Amount", "Currency",
                         "Account", "Reference", "Notes"])
        for row in rows:
            writer.writerow([row["date"], row["kind"], csv_text(row["description"]),
                             csv_text(row["category"]), decimal_amount(row["amount_cents"]),
                             row["currency"], csv_text(row["account"]), csv_text(row["reference"]),
                             csv_text(row["notes"])])


class Ledger:
    """SQLite persistence. All money is stored as integer cents, never floats."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.create_function("casefold", 1, lambda value: str(value or "").casefold())
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise ValidationError("This database was created by a different version of LedgerDesk.")
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version == 0 and tables:
                raise ValidationError("This file is not a LedgerDesk database. Choose a different data file.")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('Income','Expense')),
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    currency TEXT NOT NULL,
                    account TEXT NOT NULL,
                    reference TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_currency_date ON transactions(currency, date);
                PRAGMA user_version = 1;
            """)
            self.db.commit()
        except Exception:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def save(self, record: dict, row_id: int | None = None) -> int:
        clean = validate_record(record)
        values = [clean[field] for field in FIELDS]
        stamp = utc_now()
        with self.db:
            if row_id is None:
                placeholders = ",".join("?" for _ in range(len(FIELDS) + 2))
                result = self.db.execute(
                    f"INSERT INTO transactions ({','.join(FIELDS)},created_at,updated_at) VALUES ({placeholders})",
                    (*values, stamp, stamp))
                return int(result.lastrowid)
            result = self.db.execute(
                f"UPDATE transactions SET {','.join(field + '=?' for field in FIELDS)},updated_at=? WHERE id=?",
                (*values, stamp, row_id))
            if result.rowcount != 1:
                raise ValidationError("That transaction no longer exists. Refresh the list and try again.")
            return row_id

    def get(self, row_id: int) -> dict:
        row = self.db.execute("SELECT * FROM transactions WHERE id=?", (row_id,)).fetchone()
        if row is None:
            raise ValidationError("That transaction no longer exists.")
        return dict(row)

    def delete(self, row_id: int) -> dict:
        record = self.get(row_id)
        with self.db:
            self.db.execute("DELETE FROM transactions WHERE id=?", (row_id,))
        return record

    def undo_delete(self, record: dict) -> None:
        validate_record(record)
        columns = ("id",) + FIELDS + ("created_at", "updated_at")
        with self.db:
            self.db.execute(f"INSERT INTO transactions ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                            [record[column] for column in columns])

    def query(self, filters: Filters) -> list[dict]:
        if filters.currency not in CURRENCIES:
            raise ValidationError("Choose a supported currency.")
        conditions = ["currency=?"]
        params: list = [filters.currency]
        if filters.start:
            conditions.append("date>=?")
            params.append(parse_date(filters.start))
        if filters.end:
            conditions.append("date<=?")
            params.append(parse_date(filters.end))
        if filters.start and filters.end and filters.start > filters.end:
            raise ValidationError("The start date must be on or before the end date.")
        if filters.kind != "All types":
            if filters.kind not in CATEGORIES:
                raise ValidationError("Choose a valid transaction type.")
            conditions.append("kind=?")
            params.append(filters.kind)
        if filters.account != "All accounts":
            conditions.append("account=?")
            params.append(filters.account)
        if filters.search.strip():
            conditions.append("instr(casefold(description || ' ' || category || ' ' || account || ' ' || reference || ' ' || notes),?) > 0")
            params.append(filters.search.strip().casefold())
        rows = self.db.execute("SELECT * FROM transactions WHERE " + " AND ".join(conditions) + " ORDER BY date DESC,id DESC", params)
        return [dict(row) for row in rows]

    def accounts(self) -> list[str]:
        return [row[0] for row in self.db.execute("SELECT DISTINCT account FROM transactions ORDER BY account COLLATE NOCASE")]

    def categories(self, kind: str) -> list[str]:
        existing = [row[0] for row in self.db.execute("SELECT DISTINCT category FROM transactions WHERE kind=?", (kind,))]
        return list(dict.fromkeys([*CATEGORIES[kind], *existing]))

    def backup(self, destination: Path) -> None:
        destination = Path(destination).expanduser().resolve()
        if destination == self.path:
            raise ValidationError("Choose a backup location different from the active database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".ledger-backup-", suffix=".sqlite3", dir=destination.parent)
        os.close(handle)
        try:
            with sqlite3.connect(temporary) as copy:
                self.db.backup(copy)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def auto_backup(self) -> Path | None:
        if not self.db.execute("SELECT 1 FROM transactions LIMIT 1").fetchone():
            return None
        target = self.path.parent / "backups" / f"automatic-{date.today().isoformat()}.sqlite3"
        if not target.exists():
            self.backup(target)
        return target

    @staticmethod
    def validate_backup(path: Path) -> None:
        if not Path(path).is_file():
            raise ValidationError("Select an existing LedgerDesk backup file.")
        try:
            with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as source:
                if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValidationError("This backup is damaged. Your current data has not been changed.")
                if source.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise ValidationError("This is not a compatible LedgerDesk backup.")
                source.row_factory = sqlite3.Row
                for row in source.execute("SELECT id," + ",".join(FIELDS) + ",created_at,updated_at FROM transactions"):
                    validate_record(dict(row))
        except (sqlite3.DatabaseError, KeyError, TypeError) as exc:
            raise ValidationError("This is not a readable LedgerDesk backup. Your current data has not been changed.") from exc

    def restore(self, source_path: Path) -> Path:
        source_path = Path(source_path).expanduser().resolve()
        if source_path == self.path:
            raise ValidationError("This is the active database. Select a saved backup instead.")
        self.validate_backup(source_path)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safety = self.path.parent / "backups" / f"before-restore-{stamp}.sqlite3"
        self.backup(safety)
        with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
            source.backup(self.db)
        return safety


def totals(rows: list[dict]) -> tuple[int, int, int]:
    if len({row["currency"] for row in rows}) > 1:
        raise ValidationError("Choose one currency before calculating totals.")
    income = sum(row["amount_cents"] for row in rows if row["kind"] == "Income")
    expenses = sum(row["amount_cents"] for row in rows if row["kind"] == "Expense")
    return income, expenses, income - expenses


def load_demo(ledger: Ledger) -> None:
    start = date.today().replace(day=1)
    samples = [
        (0, "Income", "Project milestone", "Freelance", "1800.00", "Bank account"),
        (1, "Expense", "Weekly groceries", "Food & groceries", "83.40", "Card"),
        (2, "Expense", "Design software", "Subscriptions", "24.00", "Card"),
        (3, "Income", "Website maintenance", "Freelance", "350.00", "Bank account"),
        (4, "Expense", "Internet bill", "Bills & utilities", "39.90", "Bank account"),
        (5, "Expense", "Train tickets", "Transport", "18.50", "Cash"),
        (6, "Expense", "Work equipment", "Business", "145.00", "Card"),
    ]
    for days, kind, description, category, amount, account in samples:
        ledger.save(dict(date=(start + timedelta(days=min(days, date.today().day - 1))).isoformat(),
                         kind=kind, description=description, category=category,
                         amount_cents=parse_amount(amount), currency="USD", account=account,
                         reference="Sample record", notes="Demo only; no real financial records."))


# Tkinter is imported lazily so storage and export checks can run without a display.
def launch_gui(ledger: Ledger, demo: bool = False, on_ready=None) -> None:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, font as tkfont

    BG = "#F3F6F7"
    PANEL = "#FFFFFF"
    NAV = "#142832"
    TEXT = "#162F3B"
    MUTED = "#687E88"
    LINE = "#DFE7EA"
    TEAL = "#117C70"
    RED = "#BC583D"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(f"{APP_NAME} | Income & Expenses" + (" | DEMO" if demo else ""))
            self.geometry(f"{max(980, min(1280, self.winfo_screenwidth() - 60))}x"
                          f"{max(680, min(870, self.winfo_screenheight() - 80))}")
            self.minsize(980, 680)
            self.configure(bg=BG)
            self.ledger = ledger
            self.rows: list[dict] = []
            self.filters = Filters()
            self.last_deleted: dict | None = None
            self.search_job = None
            self.popup = None
            self.refresh_job = None
            available_fonts = {name.casefold(): name for name in tkfont.families()}
            self.font_name = next((available_fonts[name.casefold()]
                                   for name in ("Segoe UI", "SF Pro Text", "DejaVu Sans", "Arial", "Helvetica")
                                   if name.casefold() in available_fonts),
                                  tkfont.nametofont("TkDefaultFont").actual("family"))
            self.option_add("*Font", (self.font_name, 10))
            self.style = ttk.Style(self)
            self.style.theme_use("clam")
            self.configure_styles()
            self.build()
            self.bind("<Configure>", self.resize_layout, add="+")
            self.report_callback_exception = self.callback_error
            self.protocol("WM_DELETE_WINDOW", self.quit_app)
            self.bind("<Control-n>", lambda _e: self.add_transaction())
            self.bind("<Control-f>", self.focus_search)
            self.bind("<Control-e>", lambda _e: self.export())
            self.bind("<Control-z>", lambda _e: self.undo())
            self.bind("<F5>", lambda _e: self.apply_filters())
            self.refresh()
            if demo:
                self.set_status("DEMO SESSION  /  Sample records in a temporary database.")
            else:
                try:
                    self.ledger.auto_backup()
                except (OSError, sqlite3.Error) as exc:
                    self.set_status("Records loaded. Automatic backup could not be written: " + str(exc))

        def configure_styles(self):
            s = self.style
            s.configure("TFrame", background=BG)
            s.configure("TLabel", background=BG, foreground=TEXT, font=(self.font_name, 10))
            s.configure("TButton", font=(self.font_name, 10), padding=(12, 9), width=0, background=PANEL,
                        foreground=TEXT, borderwidth=1, bordercolor=LINE, focuscolor=TEAL)
            s.map("TButton", background=[("active", "#E8F1F0"), ("disabled", "#EDF0F1")],
                  foreground=[("disabled", "#9AA8AD")])
            s.configure("Primary.TButton", background=TEAL, foreground="white", bordercolor=TEAL,
                        font=(self.font_name, 10, "bold"))
            s.map("Primary.TButton", background=[("active", "#0B665C"), ("pressed", "#09594F")],
                  foreground=[("disabled", "#B4D0CA"), ("!disabled", "white")])
            s.configure("TEntry", padding=7, fieldbackground=PANEL, foreground=TEXT,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE)
            s.map("TEntry", bordercolor=[("focus", TEAL)])
            s.configure("TCombobox", padding=6, fieldbackground=PANEL, background=PANEL,
                        foreground=TEXT, arrowcolor=MUTED, bordercolor=LINE)
            s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
            s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=38, borderwidth=0, font=(self.font_name, 10))
            s.configure("Treeview.Heading", background="#EDF3F5", foreground=MUTED,
                        font=(self.font_name, 9, "bold"), padding=(9, 11), relief="flat")
            s.map("Treeview", background=[("selected", "#D8EEEA")], foreground=[("selected", "#124B43")])
            s.map("Treeview.Heading", background=[("active", "#E3ECEF")])
            s.configure("Vertical.TScrollbar", background="#C9D5DA", troughcolor=BG,
                        borderwidth=0, arrowsize=13)

        def label(self, parent, text="", size=10, weight="normal", color=TEXT, bg=None, **kwargs):
            if bg is None:
                bg = parent.cget("bg")
            return tk.Label(parent, text=text, font=(self.font_name, size, weight),
                            bg=bg, fg=color, anchor=kwargs.pop("anchor", "w"), **kwargs)

        def nav_button(self, parent, text, command, primary=False):
            button = tk.Button(parent, text=text, command=command, anchor="w", cursor="hand2",
                               bg="#25444D" if primary else NAV, fg="white" if primary else "#BED0D7",
                               activebackground="#284650", activeforeground="white", relief="flat",
                               bd=0, padx=15, pady=11, font=(self.font_name, 10),
                               highlightthickness=1, highlightbackground=NAV, highlightcolor="#7DCDC0")
            button.pack(fill="x", pady=3)
            return button

        def build(self):
            self.grid_columnconfigure(1, weight=1)
            self.grid_rowconfigure(0, weight=1)
            side = tk.Frame(self, bg=NAV, width=198)
            side.grid(row=0, column=0, sticky="nsew")
            side.grid_propagate(False)
            side.grid_rowconfigure(4, weight=1)
            brand = tk.Frame(side, bg=NAV)
            brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(31, 34))
            self.label(brand, "L /", 26, "bold", "#67D3BF").pack(anchor="w")
            self.label(brand, APP_NAME, 18, "bold", "white").pack(anchor="w", pady=(10, 3))
            self.label(brand, "INCOME & EXPENSES", 8, color="#92AAB4").pack(anchor="w")
            actions = tk.Frame(side, bg=NAV)
            actions.grid(row=1, column=0, sticky="ew", padx=12)
            self.nav_button(actions, "Overview", lambda: self.reset("This month"), True)
            self.nav_button(actions, "View all time", lambda: self.reset("All time"))
            self.label(side, "YOUR RECORDS", 8, "bold", "#7E9AA7").grid(row=2, column=0, sticky="w", padx=24, pady=(30, 8))
            records = tk.Frame(side, bg=NAV)
            records.grid(row=3, column=0, sticky="ew", padx=12)
            self.nav_button(records, "Export visible rows", self.export)
            self.nav_button(records, "Back up data", self.backup)
            self.nav_button(records, "Restore a backup", self.restore)
            self.nav_button(records, "Open data folder", self.open_folder)
            foot = tk.Frame(side, bg=NAV)
            foot.grid(row=5, column=0, sticky="ew", padx=24, pady=(15, 24))
            self.nav_button(foot, "Quick help", self.help)
            self.label(foot, "DEMO MODE" if demo else "LOCAL  /  OFFLINE", 8, "bold", "#7AB9AA").pack(anchor="w", pady=(15, 4))
            self.label(foot, f"Version {VERSION}", 8, color="#7E9AA7").pack(anchor="w")

            main = tk.Frame(self, bg=BG)
            main.grid(row=0, column=1, sticky="nsew", padx=26, pady=(25, 14))
            main.grid_columnconfigure(0, weight=1)
            main.grid_rowconfigure(6, weight=1)
            head = tk.Frame(main, bg=BG)
            head.grid(row=0, column=0, sticky="ew", pady=(0, 20))
            head.grid_columnconfigure(0, weight=1)
            self.label(head, "Income & expenses", 23, "bold").grid(row=0, column=0, sticky="w")
            self.subtitle = self.label(head, "A clear view of what comes in and what goes out.", color=MUTED)
            self.subtitle.grid(row=1, column=0, sticky="w", pady=(5, 0))
            ttk.Button(head, text="+  Add transaction", style="Primary.TButton",
                       command=self.add_transaction).grid(row=0, column=1, rowspan=2, sticky="e")

            controls = tk.Frame(main, bg=BG)
            controls.grid(row=1, column=0, sticky="ew", pady=(0, 16))
            self.currency = tk.StringVar(value="USD" if demo else "TRY")
            self.period = tk.StringVar(value="This month")
            self.start = tk.StringVar()
            self.end = tk.StringVar()
            start, end = period_bounds("This month")
            self.start.set(start)
            self.end.set(end)
            for col, title in enumerate(("CURRENCY", "PERIOD", "FROM  (YYYY-MM-DD)", "TO  (YYYY-MM-DD)")):
                self.label(controls, title, 8, "bold", MUTED).grid(row=0, column=col, sticky="w", pady=(0, 6), padx=(0, 12))
            currency_combo = ttk.Combobox(controls, textvariable=self.currency, values=CURRENCIES, state="readonly", width=7)
            currency_combo.grid(row=1, column=0, sticky="w", padx=(0, 12))
            currency_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
            period_combo = ttk.Combobox(controls, textvariable=self.period,
                                       values=("This month", "Last month", "This year", "All time", "Custom range"),
                                       state="readonly", width=14)
            period_combo.grid(row=1, column=1, sticky="w", padx=(0, 12))
            period_combo.bind("<<ComboboxSelected>>", self.period_changed)
            self.start_entry = ttk.Entry(controls, textvariable=self.start, width=13)
            self.start_entry.grid(row=1, column=2, padx=(0, 12), sticky="w")
            self.end_entry = ttk.Entry(controls, textvariable=self.end, width=13)
            self.end_entry.grid(row=1, column=3, padx=(0, 12), sticky="w")
            for entry in (self.start_entry, self.end_entry):
                entry.bind("<KeyRelease>", lambda _e: self.period.set("Custom range"))
                entry.bind("<Return>", lambda _e: self.apply_filters())
            ttk.Button(controls, text="Apply", command=self.apply_filters).grid(row=1, column=4, padx=(0, 7))
            ttk.Button(controls, text="Reset", command=lambda: self.reset("This month")).grid(row=1, column=5)

            cards = tk.Frame(main, bg=BG)
            cards.grid(row=2, column=0, sticky="ew", pady=(0, 16))
            self.card_values = []
            for index, (title, color, hint) in enumerate((("INCOME", TEAL, "Money received"),
                                                         ("EXPENSES", RED, "Money spent"),
                                                         ("NET CASH FLOW", TEXT, "Income minus expenses"))):
                cards.grid_columnconfigure(index, weight=1, uniform="cards")
                card = tk.Frame(cards, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
                card.grid(row=0, column=index, sticky="ew", padx=(0, 12 if index < 2 else 0))
                tk.Frame(card, bg=color, height=3).pack(fill="x")
                self.label(card, title, 8, "bold", MUTED).pack(anchor="w", padx=17, pady=(14, 6))
                value = self.label(card, "0.00", 22, "bold", color)
                value.pack(anchor="w", fill="x", padx=17)
                value.bind("<Configure>", lambda _e: self.fit_card_values())
                self.card_values.append(value)
                self.label(card, hint, 9, color=MUTED).pack(anchor="w", padx=17, pady=(6, 14))

            charts = tk.Frame(main, bg=BG)
            self.charts = charts
            self.compact = False
            charts.grid(row=3, column=0, sticky="ew", pady=(0, 17))
            charts.grid_columnconfigure(0, weight=5, uniform="charts")
            charts.grid_columnconfigure(1, weight=4, uniform="charts")
            chart1 = tk.Frame(charts, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            chart1.grid(row=0, column=0, sticky="ew", padx=(0, 12))
            self.label(chart1, "Cash flow", 11, "bold").pack(anchor="w", padx=16, pady=(13, 1))
            self.flow_canvas = tk.Canvas(chart1, bg=PANEL, height=137, highlightthickness=0)
            self.flow_canvas.pack(fill="x", padx=10, pady=(0, 8))
            chart2 = tk.Frame(charts, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            chart2.grid(row=0, column=1, sticky="ew")
            self.label(chart2, "Expense categories", 11, "bold").pack(anchor="w", padx=16, pady=(13, 1))
            self.category_canvas = tk.Canvas(chart2, bg=PANEL, height=137, highlightthickness=0)
            self.category_canvas.pack(fill="x", padx=10, pady=(0, 8))
            for canvas in (self.flow_canvas, self.category_canvas):
                canvas.bind("<Configure>", lambda _e: self.draw_charts())

            tablehead = tk.Frame(main, bg=BG)
            tablehead.grid(row=4, column=0, sticky="ew", pady=(0, 9))
            tablehead.grid_columnconfigure(0, weight=1)
            self.count_label = self.label(tablehead, "Transactions", 12, "bold")
            self.count_label.grid(row=0, column=0, sticky="w")
            self.edit_button = ttk.Button(tablehead, text="Edit", command=self.edit_transaction, state="disabled")
            self.edit_button.grid(row=0, column=1, padx=(0, 6))
            self.delete_button = ttk.Button(tablehead, text="Delete", command=self.delete_transaction, state="disabled")
            self.delete_button.grid(row=0, column=2, padx=(0, 6))
            self.undo_button = ttk.Button(tablehead, text="Undo delete", command=self.undo, state="disabled")
            self.undo_button.grid(row=0, column=3, padx=(0, 6))
            ttk.Button(tablehead, text="Export CSV", command=self.export).grid(row=0, column=4)

            findbar = tk.Frame(main, bg=BG)
            findbar.grid(row=5, column=0, sticky="ew", pady=(0, 10))
            findbar.grid_columnconfigure(0, weight=1)
            self.search = tk.StringVar()
            search_wrap = tk.Frame(findbar, bg=BG)
            search_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 10))
            self.label(search_wrap, "Search", 9, color=MUTED).pack(side="left", padx=(0, 8))
            self.search_entry = ttk.Entry(search_wrap, textvariable=self.search)
            self.search_entry.pack(side="left", fill="x", expand=True)
            self.search_entry.bind("<KeyRelease>", self.search_changed)
            self.search_entry.bind("<Return>", lambda _e: self.apply_filters())
            self.kind = tk.StringVar(value="All types")
            self.account = tk.StringVar(value="All accounts")
            kind_combo = ttk.Combobox(findbar, textvariable=self.kind, values=("All types", "Income", "Expense"),
                                     state="readonly", width=11)
            kind_combo.grid(row=0, column=1, padx=(0, 10))
            kind_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())
            self.account_combo = ttk.Combobox(findbar, textvariable=self.account, values=("All accounts",),
                                             state="readonly", width=18)
            self.account_combo.grid(row=0, column=2)
            self.account_combo.bind("<<ComboboxSelected>>", lambda _e: self.apply_filters())

            tablewrap = tk.Frame(main, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
            tablewrap.grid(row=6, column=0, sticky="nsew")
            tablewrap.grid_rowconfigure(0, weight=1)
            tablewrap.grid_columnconfigure(0, weight=1)
            columns = ("date", "description", "category", "account", "kind", "amount")
            self.table = ttk.Treeview(tablewrap, columns=columns, show="headings", selectmode="browse")
            specs = (("date", "DATE", 100, "w"), ("description", "DESCRIPTION", 230, "w"),
                     ("category", "CATEGORY", 140, "w"), ("account", "ACCOUNT", 120, "w"),
                     ("kind", "TYPE", 85, "w"), ("amount", "AMOUNT", 130, "e"))
            for column, title, width, anchor in specs:
                self.table.heading(column, text=title, anchor=anchor,
                                   command=lambda c=column: self.sort_by(c))
                self.table.column(column, width=width, minwidth=70, anchor=anchor, stretch=column == "description")
            self.table.grid(row=0, column=0, sticky="nsew")
            scroll = ttk.Scrollbar(tablewrap, orient="vertical", command=self.table.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            horizontal = ttk.Scrollbar(tablewrap, orient="horizontal", command=self.table.xview)
            horizontal.grid(row=1, column=0, sticky="ew")
            self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
            self.table.tag_configure("income", foreground=TEAL)
            self.table.tag_configure("expense", foreground=TEXT)
            self.table.bind("<<TreeviewSelect>>", self.selection_changed)
            self.table.bind("<Double-1>", lambda event: self.edit_transaction() if self.table.identify_row(event.y) else None)
            self.table.bind("<Return>", lambda _e: self.edit_transaction())
            self.table.bind("<Delete>", lambda _e: self.delete_transaction())
            self.empty_label = self.label(tablewrap, "No transactions yet.\nAdd your first income or expense.",
                                          11, color=MUTED, justify="center", anchor="center")
            self.sort_column = "date"
            self.sort_descending = True
            self.status = tk.StringVar(value="Ready. All entries save automatically on this computer.")
            self.status_label = self.label(main, "", 9, color=MUTED)
            self.status_label.config(textvariable=self.status)
            self.status_label.grid(row=7, column=0, sticky="ew", pady=(10, 0))

        def callback_error(self, _kind, value, _traceback):
            messagebox.showerror(APP_NAME, "The action could not be completed.\n\n" + str(value), parent=self)

        def resize_layout(self, event):
            if event.widget is not self:
                return
            compact = self.winfo_height() < 820
            if compact != self.compact:
                self.compact = compact
                if compact:
                    self.charts.grid_remove()
                else:
                    self.charts.grid()

        def fit_card_values(self):
            if not self.card_values or any(label.winfo_width() <= 1 for label in self.card_values):
                return
            size = 22
            measurement = tkfont.Font(family=self.font_name, size=size, weight="bold")
            while size > 8 and any(measurement.measure(label.cget("text")) > label.winfo_width() - 4
                                   for label in self.card_values):
                size -= 1
                measurement.configure(size=size)
            for label in self.card_values:
                label.configure(font=(self.font_name, size, "bold"))

        def set_status(self, message):
            self.status.set(message)

        def focus_search(self, _event=None):
            self.search_entry.focus_set()
            self.search_entry.selection_range(0, "end")
            return "break"

        def period_changed(self, _event=None):
            if self.period.get() != "Custom range":
                first, last = period_bounds(self.period.get())
                self.start.set(first)
                self.end.set(last)
                self.apply_filters()
            else:
                self.start_entry.focus_set()

        def reset(self, period):
            self.period.set(period)
            first, last = period_bounds(period)
            self.start.set(first)
            self.end.set(last)
            self.kind.set("All types")
            self.account.set("All accounts")
            self.search.set("")
            self.apply_filters()

        def search_changed(self, _event=None):
            if self.search_job is not None:
                self.after_cancel(self.search_job)
            self.search_job = self.after(300, lambda: self.apply_filters(quiet=True))

        def apply_filters(self, quiet=False):
            self.search_job = None
            candidate = Filters(self.currency.get(), self.start.get().strip(), self.end.get().strip(),
                                self.kind.get(), self.account.get(), self.search.get())
            try:
                rows = self.ledger.query(candidate)
            except (ValidationError, sqlite3.Error) as exc:
                if not quiet:
                    messagebox.showerror("Check the filters", str(exc), parent=self)
                return False
            self.filters = candidate
            self.rows = rows
            self.render_rows()
            self.set_status(f"Showing {len(rows)} transaction{'s' if len(rows) != 1 else ''} in {candidate.currency}. All entries save automatically.")
            return True

        def refresh(self):
            accounts = self.ledger.accounts()
            self.account_combo.config(values=["All accounts", *accounts])
            if self.account.get() != "All accounts" and self.account.get() not in accounts:
                self.account.set("All accounts")
            self.apply_filters()

        def render_rows(self):
            selection = self.table.selection()
            keep = selection[0] if selection else None
            self.table.delete(*self.table.get_children())
            for row in self.sorted_rows():
                sign = "+" if row["kind"] == "Income" else "-"
                self.table.insert("", "end", iid=str(row["id"]),
                                  values=(row["date"], row["description"], row["category"], row["account"],
                                          row["kind"], sign + money(row["amount_cents"])),
                                  tags=(row["kind"].lower(),))
            if keep and self.table.exists(keep):
                self.table.selection_set(keep)
            if self.rows:
                self.empty_label.place_forget()
            else:
                self.empty_label.config(text="No transactions match these filters.\nAdd an entry or adjust the dates and currency.")
                self.empty_label.place(relx=.5, rely=.58, anchor="center")
            for label, cents in zip(self.card_values, totals(self.rows)):
                label.config(text=money(cents, self.filters.currency))
            self.fit_card_values()
            self.card_values[2].config(fg=RED if totals(self.rows)[2] < 0 else TEXT)
            self.count_label.config(text=f"Transactions  /  {len(self.rows)}")
            self.subtitle.config(text=f"{self.filters.currency}  /  {self.filters.start or 'Beginning'} to {self.filters.end or 'latest entry'}  /  Current filters")
            self.selection_changed()
            self.draw_charts()

        def sorted_rows(self):
            if self.sort_column == "amount":
                key = lambda row: row["amount_cents"] * (1 if row["kind"] == "Income" else -1)
            else:
                key = lambda row: (str(row[self.sort_column]).casefold(), row["id"])
            return sorted(self.rows, key=key, reverse=self.sort_descending)

        def sort_by(self, column):
            self.sort_descending = not self.sort_descending if self.sort_column == column else column in ("date", "amount")
            self.sort_column = column
            self.render_rows()

        def selection_changed(self, _event=None):
            state = "normal" if self.table.selection() else "disabled"
            self.edit_button.config(state=state)
            self.delete_button.config(state=state)

        def selected_record(self):
            selection = self.table.selection()
            return self.ledger.get(int(selection[0])) if selection else None

        def add_transaction(self):
            if self.popup and self.popup.winfo_exists():
                self.popup.lift()
                return
            self.popup = TransactionDialog(self)

        def edit_transaction(self):
            row = self.selected_record()
            if not row:
                return
            if self.popup and self.popup.winfo_exists():
                self.popup.lift()
                return
            self.popup = TransactionDialog(self, row)

        def delete_transaction(self):
            row = self.selected_record()
            if row and messagebox.askyesno("Delete transaction?", f"Delete {row['description']}\n"
                                          f"{money(row['amount_cents'], row['currency'])} on {row['date']}?\n\n"
                                          "You can undo the most recent deletion during this session.", parent=self):
                self.last_deleted = self.ledger.delete(row["id"])
                self.undo_button.config(state="normal")
                self.refresh()
                self.set_status("Transaction deleted. Use Undo delete to restore it.")

        def undo(self):
            if self.popup and self.popup.winfo_exists():
                return
            if self.last_deleted:
                self.ledger.undo_delete(self.last_deleted)
                self.last_deleted = None
                self.undo_button.config(state="disabled")
                self.refresh()
                self.set_status("Deleted transaction restored.")

        def export(self):
            if not self.apply_filters():
                return
            if not self.rows:
                messagebox.showinfo("Nothing to export", "Add a transaction or adjust the filters first.", parent=self)
                return
            target = filedialog.asksaveasfilename(parent=self, title="Export visible transactions", defaultextension=".csv",
                                                initialfile=f"transactions-{self.filters.currency}-{date.today().isoformat()}.csv",
                                                filetypes=[("CSV file", "*.csv")])
            if target:
                if Path(target).resolve() == self.ledger.path:
                    raise ValidationError("Choose a different filename; this is the active database.")
                export_csv(Path(target), self.sorted_rows())
                self.set_status(f"Exported {len(self.rows)} transactions to {Path(target).name}.")

        def backup(self):
            target = filedialog.asksaveasfilename(parent=self, title="Save a full backup", defaultextension=".sqlite3",
                                                initialfile=f"LedgerDesk-backup-{date.today().isoformat()}.sqlite3",
                                                filetypes=[("LedgerDesk backup", "*.sqlite3")])
            if target:
                self.ledger.backup(Path(target))
                self.set_status("Full backup saved: " + Path(target).name)
                messagebox.showinfo("Backup saved", "All currencies and all transactions were backed up.\n\n" + target, parent=self)

        def restore(self):
            source = filedialog.askopenfilename(parent=self, title="Choose a LedgerDesk backup",
                                              filetypes=[("LedgerDesk backup", "*.sqlite3"), ("All files", "*")])
            if not source:
                return
            self.ledger.validate_backup(Path(source))
            if messagebox.askyesno("Restore backup?", "Replace the current ledger with this backup?\n\n"
                                  "A safety copy of your current records will be kept in the backups folder.", parent=self):
                safety = self.ledger.restore(Path(source))
                self.last_deleted = None
                self.undo_button.config(state="disabled")
                self.reset("All time")
                self.refresh()
                self.set_status("Backup restored. Previous data saved as " + safety.name)

        def open_folder(self):
            folder = str(self.ledger.path.parent)
            try:
                if sys.platform == "win32":
                    os.startfile(folder)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                messagebox.showinfo("Data folder", folder, parent=self)

        def help(self):
            messagebox.showinfo("Quick help", "Add income and expenses with + Add transaction.\n"
                                "Double-click a row to view or edit its full details.\n"
                                "Choose a currency and dates, then Apply. Blank dates mean no date limit.\n"
                                "Search also checks notes and references. Click a column heading to sort.\n\n"
                                "Totals and charts follow every active filter. Net cash flow is income minus expenses.\n"
                                "Currencies are kept separate; no exchange rates are applied.\n\n"
                                "Export CSV saves visible rows. Back up data saves the whole ledger.\n"
                                "A daily snapshot is saved on launch when records exist.\n\n"
                                "Ctrl+N: add  |  Ctrl+F: search  |  Ctrl+E: export  |  Ctrl+Z: undo deletion\n\n"
                                "Your data folder:\n" + str(self.ledger.path.parent), parent=self)

        def draw_charts(self):
            if not hasattr(self, "flow_canvas"):
                return
            self.draw_cash_flow()
            self.draw_categories()

        def draw_cash_flow(self):
            canvas = self.flow_canvas
            canvas.delete("all")
            width = max(canvas.winfo_width(), 260)
            if not self.rows:
                canvas.create_text(width / 2, 65, text="Your cash flow will appear here.",
                                   font=(self.font_name, 10), fill=MUTED)
                return
            canvas.create_rectangle(width - 155, 8, width - 147, 16, fill=TEAL, outline="")
            canvas.create_text(width - 142, 12, text="Income", anchor="w", fill=MUTED, font=(self.font_name, 8))
            canvas.create_rectangle(width - 78, 8, width - 70, 16, fill="#D48468", outline="")
            canvas.create_text(width - 65, 12, text="Expenses", anchor="w", fill=MUTED, font=(self.font_name, 8))
            first = min(row["date"] for row in self.rows)
            last = max(row["date"] for row in self.rows)
            first_day, last_day = date.fromisoformat(first), date.fromisoformat(last)
            days = (last_day - first_day).days + 1
            buckets = []
            if days <= 31:
                count = min(days, 6)
                span = (days + count - 1) // count
                for index in range(count):
                    begin = first_day + timedelta(days=index * span)
                    if begin > last_day:
                        break
                    finish = min(begin + timedelta(days=span - 1), last_day)
                    label = begin.strftime("%d %b")
                    bucket_rows = [r for r in self.rows if begin.isoformat() <= r["date"] <= finish.isoformat()]
                    inc, exp, _ = totals(bucket_rows)
                    buckets.append((label, inc, exp))
            else:
                months = (last_day.year - first_day.year) * 12 + last_day.month - first_day.month + 1
                size = max(1, (months + 5) // 6)
                for index in range(0, months, size):
                    begin = shift_month(first_day, index)
                    finish = shift_month(begin, size) - timedelta(days=1)
                    bucket_rows = [r for r in self.rows if begin.isoformat() <= r["date"] <= finish.isoformat()]
                    inc, exp, _ = totals(bucket_rows)
                    label = begin.strftime("%b %y") if size == 1 else begin.strftime("%b %y") + "+"
                    buckets.append((label, inc, exp))
            maximum = max(max(inc, exp) for _, inc, exp in buckets) or 1
            left, right, bottom, height = 16, width - 15, 106, 68
            canvas.create_line(left, bottom, right, bottom, fill=LINE)
            step = (right - left) / len(buckets)
            bar_width = min(22, step / 3)
            for index, (label, inc, exp) in enumerate(buckets):
                center = left + (index + .5) * step
                for offset, amount, color in ((-bar_width - 1, inc, TEAL), (1, exp, "#D48468")):
                    if amount:
                        canvas.create_rectangle(center + offset, bottom - height * amount / maximum,
                                                center + offset + bar_width, bottom, fill=color, outline="")
                canvas.create_text(center, bottom + 16, text=label, fill=MUTED, font=(self.font_name, 8))
            canvas.create_text(left, 12, text="Filtered period", anchor="w", fill=MUTED, font=(self.font_name, 8))

        def draw_categories(self):
            canvas = self.category_canvas
            canvas.delete("all")
            width = max(canvas.winfo_width(), 240)
            groups: dict[str, int] = {}
            for row in self.rows:
                if row["kind"] == "Expense":
                    groups[row["category"]] = groups.get(row["category"], 0) + row["amount_cents"]
            if not groups:
                canvas.create_text(width / 2, 65, text="No expenses in this view.",
                                   font=(self.font_name, 10), fill=MUTED)
                return
            ordered = sorted(groups.items(), key=lambda item: item[1], reverse=True)
            if len(ordered) > 4:
                ordered = ordered[:3] + [("Other categories", sum(value for _, value in ordered[3:]))]
            maximum = max(value for _, value in ordered)
            for index, (name, amount) in enumerate(ordered):
                y = index * 31 + 9
                label = name if len(name) <= 25 else name[:24] + "…"
                canvas.create_text(6, y, text=label, anchor="w", fill=TEXT, font=(self.font_name, 8))
                canvas.create_text(width - 8, y, text=money(amount), anchor="e", fill=MUTED, font=(self.font_name, 8))
                canvas.create_rectangle(6, y + 10, width - 8, y + 15, fill="#EAF1F2", outline="")
                canvas.create_rectangle(6, y + 10, 6 + (width - 14) * amount / maximum, y + 15, fill="#3A9B8F", outline="")

        def quit_app(self):
            if self.popup and self.popup.winfo_exists():
                self.popup.lift()
                return
            self.destroy()

    class TransactionDialog(tk.Toplevel):
        def __init__(self, app, record=None):
            super().__init__(app)
            self.app = app
            self.record = record
            self.title("Edit transaction" if record else "Add transaction")
            self.configure(bg=BG)
            self.resizable(False, False)
            self.transient(app)
            self.protocol("WM_DELETE_WINDOW", self.cancel)
            self.grab_set()
            form = tk.Frame(self, bg=BG)
            form.pack(fill="both", expand=True, padx=26, pady=22)
            app.label(form, "Edit transaction" if record else "New transaction", 19, "bold").grid(row=0, column=0, columnspan=2, sticky="w")
            app.label(form, "Enter the amount as a positive number. Type sets the direction.", 9, color=MUTED).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 17))
            initial = record or dict(date=date.today().isoformat(), kind="Expense", description="", category="Food & groceries",
                                     amount_cents=0, currency=app.currency.get(), account="Bank account", reference="", notes="")
            self.variables = {key: tk.StringVar(value=initial[key]) for key in FIELDS if key not in ("amount_cents", "notes")}
            self.amount = tk.StringVar(value=decimal_amount(initial["amount_cents"]) if record else "")

            def form_label(text, row, col=0):
                app.label(form, text, 9, "bold", MUTED).grid(row=row, column=col, sticky="w", pady=(9, 5), padx=(0, 13))

            form_label("TYPE", 2)
            form_label("DATE  /  YYYY-MM-DD", 2, 1)
            self.kind_combo = ttk.Combobox(form, textvariable=self.variables["kind"], values=("Income", "Expense"), state="readonly", width=24)
            self.kind_combo.grid(row=3, column=0, sticky="ew", padx=(0, 13))
            self.kind_combo.bind("<<ComboboxSelected>>", self.kind_changed)
            ttk.Entry(form, textvariable=self.variables["date"], width=24).grid(row=3, column=1, sticky="ew")
            form_label("DESCRIPTION", 4)
            self.description_entry = ttk.Entry(form, textvariable=self.variables["description"])
            self.description_entry.grid(row=5, column=0, columnspan=2, sticky="ew")
            form_label("AMOUNT", 6)
            form_label("CURRENCY", 6, 1)
            self.amount_entry = ttk.Entry(form, textvariable=self.amount)
            self.amount_entry.grid(row=7, column=0, sticky="ew", padx=(0, 13))
            ttk.Combobox(form, textvariable=self.variables["currency"], values=CURRENCIES, state="readonly").grid(row=7, column=1, sticky="ew")
            form_label("CATEGORY  /  CHOOSE OR TYPE", 8)
            form_label("ACCOUNT  /  CHOOSE OR TYPE", 8, 1)
            self.category_combo = ttk.Combobox(form, textvariable=self.variables["category"], values=app.ledger.categories(initial["kind"]))
            self.category_combo.grid(row=9, column=0, sticky="ew", padx=(0, 13))
            accounts = list(dict.fromkeys(["Bank account", "Cash", "Card", *app.ledger.accounts()]))
            ttk.Combobox(form, textvariable=self.variables["account"], values=accounts).grid(row=9, column=1, sticky="ew")
            form_label("REFERENCE  /  OPTIONAL", 10)
            ttk.Entry(form, textvariable=self.variables["reference"]).grid(row=11, column=0, columnspan=2, sticky="ew")
            form_label("NOTES  /  OPTIONAL", 12)
            self.notes = tk.Text(form, height=3, width=51, wrap="word", font=(app.font_name, 10), bg=PANEL, fg=TEXT,
                                 insertbackground=TEAL, relief="flat", highlightthickness=1, highlightbackground=LINE, highlightcolor=TEAL,
                                 padx=9, pady=7, undo=True)
            self.notes.grid(row=13, column=0, columnspan=2, sticky="ew")
            self.notes.insert("1.0", initial["notes"])
            buttons = tk.Frame(form, bg=BG)
            buttons.grid(row=14, column=0, columnspan=2, sticky="e", pady=(20, 0))
            ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side="left", padx=(0, 9))
            ttk.Button(buttons, text="Save changes" if record else "Save transaction", style="Primary.TButton", command=self.save).pack(side="left")
            self.bind("<Escape>", lambda _e: self.cancel())
            self.bind("<Control-Return>", lambda _e: self.save())
            self.update_idletasks()
            x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
            y = app.winfo_rooty() + max(15, (app.winfo_height() - self.winfo_reqheight()) // 2)
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
            self.description_entry.focus_set()

        def kind_changed(self, _event=None):
            categories = self.app.ledger.categories(self.variables["kind"].get())
            self.category_combo.config(values=categories)
            if self.variables["category"].get() not in categories:
                self.variables["category"].set(categories[0])

        def save(self):
            try:
                record = {key: variable.get() for key, variable in self.variables.items()}
                record["amount_cents"] = parse_amount(self.amount.get())
                record["notes"] = self.notes.get("1.0", "end-1c")
                row_id = self.app.ledger.save(record, self.record["id"] if self.record else None)
            except (ValidationError, sqlite3.Error, OSError) as exc:
                messagebox.showerror("Check the transaction", str(exc), parent=self)
                return
            self.app.currency.set(record["currency"])
            self.app.refresh()
            if self.app.table.exists(str(row_id)):
                self.app.table.selection_set(str(row_id))
                self.app.table.see(str(row_id))
                self.app.set_status("Transaction saved.")
            else:
                self.app.set_status("Transaction saved. It is outside the active filters; choose View all time to see it.")
            self.cancel()

        def cancel(self):
            self.grab_release()
            self.app.popup = None
            self.destroy()

    app = App()
    if on_ready is not None:
        app.after(100, lambda: on_ready(app, TransactionDialog))
    app.mainloop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="An offline desktop income and expense tracker.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--data-file", type=Path, help="use a specific SQLite data file")
    group.add_argument("--demo", action="store_true", help="open temporary sample records; never uses your real ledger")
    parser.add_argument("--self-test-report", type=Path, metavar="JSON_FILE",
                        help="test the packaged runtime and GUI with temporary data, then write a JSON report")
    args = parser.parse_args(argv)
    if args.self_test_report:
        return packaged_self_test(args.self_test_report)
    demo_folder = tempfile.TemporaryDirectory(prefix="ledgerdesk-demo-") if args.demo else None
    ledger = None
    try:
        data_file = Path(demo_folder.name) / "demo.sqlite3" if demo_folder else (args.data_file or default_data_file())
        ledger = Ledger(data_file)
        if args.demo:
            load_demo(ledger)
        launch_gui(ledger, args.demo)
        return 0
    except Exception as exc:
        print(f"{APP_NAME} could not start: {exc}", file=sys.stderr)
        try:
            from tkinter import Tk, messagebox
            root = Tk()
            root.withdraw()
            messagebox.showerror(APP_NAME, "The app could not start.\n\n" + str(exc) +
                                 "\n\nUse Python 3.10 or later with Tcl/Tk installed.", parent=root)
            root.destroy()
        except Exception:
            pass
        return 1
    finally:
        if ledger is not None:
            ledger.close()
        if demo_folder:
            demo_folder.cleanup()


def packaged_self_test(report_path: Path) -> int:
    """Exercise the distributed Python, Tk, SQLite, and CSV stack without using the real ledger."""
    import json
    import traceback
    from contextlib import closing
    report = {"app": APP_NAME, "version": VERSION, "python": sys.version,
              "platform": sys.platform, "status": "failed", "checks": []}
    ledger = None
    try:
        with tempfile.TemporaryDirectory(prefix="ledgerdesk-check-") as folder, \
             closing(Ledger(Path(folder) / "check.sqlite3")) as ledger:
            sample = dict(date=date.today().isoformat(), kind="Income", description="Runtime check — Türkçe",
                          category="Freelance", amount_cents=30, currency="USD", account="Test account",
                          reference="000001", notes="Isolated runtime check.")
            row_id = ledger.save(sample)
            if totals(ledger.query(Filters("USD"))) != (30, 0, 30):
                raise RuntimeError("The currency and amount check failed.")
            sample["amount_cents"] = 1234
            ledger.save(sample, row_id)
            removed = ledger.delete(row_id)
            ledger.undo_delete(removed)
            export_path = Path(folder) / "check.csv"
            export_csv(export_path, ledger.query(Filters("USD")))
            if "12.34" not in export_path.read_text(encoding="utf-8-sig"):
                raise RuntimeError("The CSV check failed.")
            backup = Path(folder) / "backup.sqlite3"
            ledger.backup(backup)
            ledger.delete(row_id)
            ledger.restore(backup)
            if ledger.get(row_id)["reference"] != "000001":
                raise RuntimeError("The backup and restore check failed.")
            report["checks"] += ["sqlite", "exact amounts", "edit", "delete and undo", "csv", "backup and restore"]
            gui_errors = []

            def check_window(app, _dialog_class):
                try:
                    app.update_idletasks()
                    if len(app.rows) != 1:
                        raise RuntimeError("The GUI did not load the test ledger.")
                    app.add_transaction()
                    app.popup.update_idletasks()
                    app.popup.cancel()
                    report["checks"] += ["tk window", "transaction dialog"]
                except Exception:
                    gui_errors.append(traceback.format_exc())
                finally:
                    app.destroy()

            launch_gui(ledger, demo=True, on_ready=check_window)
            if gui_errors:
                raise RuntimeError(gui_errors[0])
            report["status"] = "passed"
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if ledger is not None:
            ledger.close()
        report_path = Path(report_path).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
