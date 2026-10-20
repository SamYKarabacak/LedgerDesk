#!/bin/sh
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
    echo "Install Python 3.10 or later with Tcl/Tk from python.org."
    read -r ignored
    exit 1
fi
python3 income_tracker.py "$@"
result=$?
if [ "$result" -ne 0 ]; then
    echo "LedgerDesk could not start. See the error above and README.md."
    read -r ignored
fi
exit "$result"
