# LedgerDesk 1.1.0 verification

Checked on 20 October 2026. The build environment is Linux with Python 3.12.14
and Tcl/Tk 9.0; the portable package targets Windows 10/11 x64 and bundles the
official CPython 3.14.8 runtime plus its matching Tcl/Tk files.

| Check | Result |
| --- | --- |
| Data, export, and build-output protection checks | 18 passed |
| Live Tk add/edit/filter/delete/undo/export/backup/restore workflow | Passed on Linux |
| Isolated runtime/GUI self-test | Passed on Linux; report in docs/source-self-test.json |
| Python wheel build from pyproject.toml | Passed |
| Project metadata and workflow YAML structure | Checked |
| Upstream runtime downloads | Both matched locked SHA-256 values |
| Native Windows launcher compilation | Passed with warnings treated as errors |
| EXE and bundled runtime architecture | PE x64; GUI subsystem verified |
| Launcher runtime imports | KERNEL32.dll, msvcrt.dll, USER32.dll |
| Bundle completeness and ZIP integrity | Passed |
| Native Windows execution | Not performed in this environment |
| GitHub Actions execution | Workflow included; not run against a hosted repository here |

The delivered Windows EXE was compiled, not merely renamed from a Python file.
Its app and runtime folders are included in the runnable ZIP. A Windows
compatibility runtime could not initialize here because the host blocks the
required sockets; it did not reach application execution.

The included GitHub workflow builds the package and launches the actual EXE
on a Windows runner from a path containing spaces and Unicode. That check
must pass before the workflow prepares a draft release. It exercises the
bundled Tk window and dialog, SQLite, edits, delete/undo, CSV, and backups.

The overview, transaction dialog, and compact layouts were visually inspected
at 1280 x 870, 1120 x 780, and 980 x 680. The source tests cover exact monetary
arithmetic, invalid inputs, inclusive dates, currency separation, reopening,
literal text searches, atomic edits, undo, complete backups and safety copies,
invalid-backup rejection, daily snapshots, Unicode export, spreadsheet-formula
protection, and safe build-output replacement.

The release contains no personal financial database. Preview and demo records
are fictional. Existing 1.0.0 ledgers use the same database schema and data path.
