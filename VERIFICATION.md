# LedgerDesk 1.1.0 verification

Verified on 20 October 2026. The released Windows x64 ZIP includes CPython
3.14.8 and its matching Tcl/Tk runtime.

| Check | Result |
| --- | --- |
| Data, export, backup, and build-output protection checks | 19 passed per job on Linux and Windows, with Python 3.10 and 3.14 |
| Portable Windows launcher compilation and packaging | Passed |
| Locked upstream runtime hashes | Matched |
| Released ZIP checksum and source comparison | Passed |
| Actual released EXE on Windows Server 2022 | Passed |
| Bundled Tk window and transaction dialog | Passed |
| Bundled SQLite, exact amounts, edit, delete/undo, CSV, backup/restore | Passed |
| Earlier live GUI workflow and layout review | Passed on Linux |

[Source tests and complete build workflow](https://github.com/SamYKarabacak/LedgerDesk/actions/runs/39495569553).

[Verification of the exact released ZIP and publication](https://github.com/SamYKarabacak/LedgerDesk/actions/runs/39495753949).

The Windows check downloaded the saved build package, verified its SHA-256
and its bundled source against the repository, then launched LedgerDesk.exe
from a folder containing spaces and Unicode. The EXE exercised its private
Python, Tk, and SQLite runtime with temporary records. It did not use a real
ledger. Its report is in [docs/windows-self-test.json](docs/windows-self-test.json).

The released ZIP has SHA-256
`57418ba6e0a50951ed93fba2523e77ee9e3d9ab15cf2d63b812d389bd9b36f0b`.
The checksum file is included in the release and in `release-checksums/`.

The source tests cover exact monetary arithmetic, invalid inputs, inclusive
dates, currency separation, reopening, literal text searches, atomic edits,
undo, complete backups and safety copies, backup-file moves after validation
and restore, invalid-backup rejection, daily snapshots, Unicode CSV export,
spreadsheet-formula protection, and safe build-output replacement.

The release includes no personal financial database. Preview and demo records
are fictional. Existing 1.0.0 ledgers use the same database schema and data path.
