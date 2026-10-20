# Put LedgerDesk on GitHub

You have two deliverables: the source project and a ready-to-run Windows ZIP.

## Upload the project

1. Create an empty GitHub repository, for example **LedgerDesk**.
2. Extract the source-project ZIP.
3. Upload the contents of its **LedgerDesk** folder into the repository root.
   Include **.github/workflows/build.yml** to install the build automation.
   README.md should sit at the repository root.
4. Commit the upload to main.

With Git installed, run these commands in the project folder after replacing
the URL with the empty repository's actual URL:

```sh
git init -b main
git add .
git commit -m "Add LedgerDesk desktop application"
git remote add origin https://github.com/YOUR_USERNAME/LedgerDesk.git
git push -u origin main
```

.gitignore excludes financial databases, CSVs, logs, build outputs, and the
build cache from future commits.

## Make the app downloadable

Open **Releases → Draft a new release**. Use tag `v1.1.0`, attach
**LedgerDesk-v1.1.0-Windows-x64.zip** as a release asset, and publish when ready.
Include its `.sha256` file if available. Visitors download the ZIP, extract it,
and open **LedgerDesk.exe**. Share the whole ZIP with its runtime folders.

The source project belongs under Code; the runnable Windows ZIP belongs in Releases.

## Build future versions

Open **Actions → Build Windows app → Run workflow**. After the build and EXE
self-test pass, open the run and download **LedgerDesk-Windows-x64** from
Artifacts. Inside is the application ZIP and checksum.

For an automatic draft release:

```sh
git tag v1.1.0
git push origin v1.1.0
```

The tag must match VERSION in income_tracker.py. The workflow creates a draft
after source tests and native Windows checks pass. If a release already
exists, it leaves that release in place; the new build remains in Artifacts.
The workflow uses GitHub's automatic token and requests write access only for
creating a draft release. No personal access token is required.
