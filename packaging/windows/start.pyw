"""Portable application bootstrap. The native launcher starts this with Python -I."""
from pathlib import Path
import os
import sys
import traceback

APP_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))
if os.name == "nt":
    # Keep Tcl/Tk's supporting DLLs in the same explicit private search path.
    dll_folder = PACKAGE_DIR / "runtime" / "DLLs"
    dll_cookie = os.add_dll_directory(str(dll_folder))

try:
    from income_tracker import main
    status = main()
except Exception:
    message = traceback.format_exc()
    if "--self-test-report" in sys.argv:
        import json
        position = sys.argv.index("--self-test-report") + 1
        if position < len(sys.argv):
            report = Path(sys.argv[position])
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json.dumps({"status": "failed", "error": message}, indent=2), encoding="utf-8")
    else:
        log_folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LedgerDesk"
        try:
            log_folder.mkdir(parents=True, exist_ok=True)
            (log_folder / "startup.log").write_text(message, encoding="utf-8")
        except OSError:
            pass
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "LedgerDesk could not start.\n\n"
                                        "Extract the complete download and try again.\n"
                                        "Details are recorded in the LedgerDesk data folder.", "LedgerDesk", 16)
    status = 1
raise SystemExit(status)
