# Building and publishing LedgerDesk

The repository holds the source. Ready-to-run Windows packages and checksums
are attached to [releases](https://github.com/SamYKarabacak/LedgerDesk/releases).

## Work on the source

Clone the repository and run it with Python 3.10+ and Tcl/Tk:

```sh
git clone https://github.com/SamYKarabacak/LedgerDesk.git
cd LedgerDesk
python income_tracker.py
```

Use `python income_tracker.py --demo` for temporary sample records.
`.gitignore` excludes databases, CSV exports, logs, build outputs, and the
build cache. Check the files you are committing before pushing.

Run the source tests with:

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

## Build a Windows package

Open **Actions → Build Windows app → Run workflow**. The workflow runs the
source tests on Linux and Windows, builds the portable package, and tests the
packaged EXE on Windows.

After the run passes, download **LedgerDesk-Windows-x64** from its Artifacts.
It contains the application ZIP and its SHA-256 checksum. Extract the complete
application ZIP and open `LedgerDesk.exe`; keep its `app` and `runtime`
folders beside it.

[VERIFICATION.md](VERIFICATION.md) records checks for the published 1.1.0 ZIP.
A new build has its own workflow results and checksum.

## Publish a new version

1. Update `VERSION` in `income_tracker.py`, package metadata, release notes,
   and documentation for the new version.
2. Commit and push the changes.
3. Create and push a new `vX.Y.Z` tag matching `VERSION`.
4. Wait for the source tests, package build, and Windows EXE checks to pass.
5. Review the draft release, its notes, ZIP, and checksum, then publish it.

The workflow validates the tag before preparing a draft. If a release already
exists for that tag, it leaves the release in place and keeps the new build
in Actions artifacts.

Release automation uses GitHub's built-in token. Write permission is limited
to the draft-release job; no personal access token is required.
