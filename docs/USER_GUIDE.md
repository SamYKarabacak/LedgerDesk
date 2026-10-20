# Using LedgerDesk

For the portable Windows edition, extract the complete download and open
**LedgerDesk.exe**. Source users can launch `python income_tracker.py` with
Python 3.10+ and Tcl/Tk installed.

## Add and edit transactions

Choose **+ Add transaction**, then select Income or Expense. Enter a date,
description, positive amount, currency, category, and account. Reference and
notes are optional. Category and account fields accept your own names.

Amounts accept `1250.50` or `1250,50`; omit currency symbols and thousands
separators. Dates use `YYYY-MM-DD`. Future-dated records count when they fall
inside your selected date range. Each saved entry is written immediately.

Double-click a row to read or edit its complete details. Delete asks for
confirmation. Undo delete restores the most recent deletion during the current
session until you delete another record or restore a backup.

## Totals and filters

TRY, USD, EUR, GBP, CAD, and CHF each have a separate view. No exchange rates
or conversions are applied. Amounts use integer cents with two decimal places.

Choose dates, type, account, or search text to narrow the view. Press Apply
after editing dates; a blank date removes that boundary. View all time resets
other filters while keeping the currency. Search checks descriptions,
categories, accounts, references, and notes. Click column titles to sort.

Cards and charts follow all active filters. Choosing Expense hides income and
produces negative net cash flow for that view. Net cash flow is income minus
expenses in the selected records; it is not a bank balance or opening balance.

Cash flow uses up to six date buckets. A `+` after a month label means the
bucket spans multiple months. Categories use up to four groups, combining
smaller categories as Other categories. Shorter windows hide chart panels to
leave more room for transactions.

## Export CSV

Export CSV saves visible rows, including full references and notes, using
UTF-8 with a BOM for Excel. Amounts remain positive; Type records their
direction. Currency is a separate column. Text that could run as a spreadsheet
formula is prefixed with an apostrophe. CSV and bank-statement imports are not
included in this version.

## Back up and restore

Back up data creates a full `.sqlite3` copy across all currencies and dates,
regardless of filters. Keep another copy in your own backup location.

Restore a backup validates the file, asks for confirmation, saves a safety
copy of the current database in its backups subfolder, then replaces the
ledger. Restore is replacement, not merging. Restore the safety copy if needed.
Undo deletion is cleared after a restore.

At launch, when records exist, a daily snapshot is created at most once per
day. It captures records present when that day's first snapshot is created.
New entries keep saving to the active database. Snapshots stay in the backups
subfolder and are not automatically deleted.

## Locate your records

Use Open data folder. The defaults are:

| System | Database |
| --- | --- |
| Windows | `%LOCALAPPDATA%\LedgerDesk\ledger.sqlite3` |
| macOS source edition | `~/Library/Application Support/LedgerDesk/ledger.sqlite3` |
| Linux source edition | `$XDG_DATA_HOME/LedgerDesk/ledger.sqlite3` or `~/.local/share/LedgerDesk/ledger.sqlite3` |

Replacing the app folder preserves the separately stored ledger. Files and
exports are unencrypted. The app does not upload, sync, or connect to a bank.
Keep one window open for a given ledger while editing or restoring.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N | Add transaction |
| Ctrl+F | Search |
| Ctrl+E | Export visible rows |
| Ctrl+Z | Undo the latest deletion from the main window |
| F5 | Apply filters and refresh |
| Enter on a row | Edit |
| Ctrl+Enter in the entry dialog | Save |
| Escape in the entry dialog | Cancel |

Launch with `--data-file PATH` for a separate ledger. Launch with `--demo`
for fictional records in a temporary database removed when the session closes.
Demo mode does not open the real ledger.
