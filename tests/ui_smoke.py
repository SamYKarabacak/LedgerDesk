"""Exercise real Tk widgets on a graphical display; screenshots use optional Pillow."""
from pathlib import Path
import os
import sys
import tempfile
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from income_tracker import Ledger, Filters, load_demo, launch_gui, totals


def main():
    failures = []
    errors = []
    with tempfile.TemporaryDirectory(prefix="ledgerdesk-ui-") as folder:
        root = Path(folder)
        ledger = Ledger(root / "ledger.sqlite3")
        load_demo(ledger)

        def exercise(app, dialog_class):
            try:
                from tkinter import font as tkfont
                app.update_idletasks()
                app.update()
                print('UI font:', app.font_name, '| available:', sorted(tkfont.families())[:18],
                      '| 23pt metrics:', tkfont.Font(family=app.font_name, size=23).metrics())
                assert len(app.rows) == 7
                assert totals(app.rows) == (215000, 31080, 183920)
                assert app.table.winfo_height() >= 120
                capture = os.environ.get("LEDGERDESK_SCREENSHOT")
                if capture:
                    from PIL import ImageGrab
                    x, y = app.winfo_rootx(), app.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()),
                                   xdisplay=os.environ.get("DISPLAY")).save(capture)

                app.add_transaction()
                dialog = app.popup
                assert dialog.winfo_exists()
                dialog.variables["description"].set("UI test — Türkçe")
                dialog.variables["kind"].set("Income")
                dialog.kind_changed()
                dialog.variables["currency"].set("USD")
                dialog.variables["account"].set("UI bank")
                dialog.variables["reference"].set("000123")
                dialog.amount.set("0,30")
                dialog.notes.insert("1.0", "Saved through the interface.")
                app.update()
                if capture:
                    from PIL import ImageGrab
                    x, y = dialog.winfo_rootx(), dialog.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + dialog.winfo_width(), y + dialog.winfo_height()),
                                   xdisplay=os.environ.get("DISPLAY")).save(str(Path(capture).with_name("preview-dialog.png")))
                dialog.save()
                assert app.popup is None
                new = next(row for row in app.rows if row["description"] == "UI test — Türkçe")
                assert new["amount_cents"] == 30
                assert new["category"] == "Freelance"

                app.table.selection_set(str(new["id"]))
                app.edit_transaction()
                app.popup.amount.set("12.34")
                app.popup.save()
                assert ledger.get(new["id"])["amount_cents"] == 1234

                app.search.set("000123")
                app.apply_filters()
                assert len(app.rows) == 1
                export_path = root / "visible.csv"
                with patch("tkinter.filedialog.asksaveasfilename", return_value=str(export_path)):
                    app.export()
                assert "UI test" in export_path.read_text(encoding="utf-8-sig")

                app.table.selection_set(str(new["id"]))
                with patch("tkinter.messagebox.askyesno", return_value=True):
                    app.delete_transaction()
                assert not app.rows
                app.undo()
                assert len(app.rows) == 1

                app.reset("This month")
                app.account.set("UI bank")
                app.apply_filters()
                assert len(app.rows) == 1
                app.reset("This month")
                assert len(app.rows) == 8
                app.currency.set("TRY")
                app.apply_filters()
                assert app.rows == []
                assert app.card_values[0].cget("text") == "TRY 0.00"
                app.currency.set("USD")
                app.apply_filters()

                backup_path = root / "manual.sqlite3"
                with patch("tkinter.filedialog.asksaveasfilename", return_value=str(backup_path)):
                    app.backup()
                ledger.delete(new["id"])
                app.refresh()
                assert len(app.rows) == 7
                with patch("tkinter.filedialog.askopenfilename", return_value=str(backup_path)), \
                     patch("tkinter.messagebox.askyesno", return_value=True):
                    app.restore()
                assert len(app.rows) == 8
                assert app.last_deleted is None

                app.sort_by("amount")
                app.sort_by("description")
                app.geometry("1120x780")
                app.update_idletasks()
                app.update()
                if capture:
                    from PIL import ImageGrab
                    x, y = app.winfo_rootx(), app.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height()),
                                   xdisplay=os.environ.get("DISPLAY")).save(str(Path(capture).with_name("preview-minimum.png")))
                assert app.table.winfo_height() >= 180
                assert app.compact
                app.geometry("980x680")
                app.update()
                assert app.table.winfo_height() >= 100
                assert not errors, errors
                print("UI PASS: add, edit, search, filter, delete, undo, CSV export, backup, restore, sort, resize.")
            except Exception:
                failures.append(traceback.format_exc())
            finally:
                app.destroy()

        try:
            with patch("tkinter.messagebox.showerror", side_effect=lambda *a, **k: errors.append(str(a))), \
                 patch("tkinter.messagebox.showinfo", return_value=None):
                launch_gui(ledger, demo=True, on_ready=exercise)
        finally:
            ledger.close()
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
