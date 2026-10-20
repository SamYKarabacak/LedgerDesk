@echo off
setlocal
cd /d "%~dp0"
title LedgerDesk - Income and Expenses
where py >nul 2>nul
if errorlevel 1 goto try_python
py -3 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto try_python
py -3 "%~dp0income_tracker.py" %*
if errorlevel 1 goto failed
exit /b 0

:try_python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto missing
python "%~dp0income_tracker.py" %*
if errorlevel 1 goto failed
exit /b 0

:missing
echo LedgerDesk needs Python 3.10 or later with Tcl/Tk.
echo Install Python from https://www.python.org/downloads/windows/
echo Keep the Tcl/Tk option selected and enable "Add Python to PATH".
echo Then run this launcher again.
pause
exit /b 1

:failed
echo.
echo LedgerDesk could not start. Read the error above.
echo See README.md for help. Your saved records stay in your data folder.
pause
exit /b 1
