@echo off
setlocal
cd /d "%~dp0"
:pick_log
set "inventory_scan_log=vm-inventory-scan-%RANDOM%-%RANDOM%.txt"
if exist "%inventory_scan_log%" goto pick_log
where py >nul 2>nul
if errorlevel 1 (python collect_virtualbox.py > "%inventory_scan_log%" 2>&1) else (py -3 collect_virtualbox.py > "%inventory_scan_log%" 2>&1)
set "inventory_scan_exit=%errorlevel%"
type "%inventory_scan_log%"
echo.
echo Scan output saved in %inventory_scan_log%
echo Results remain on disk after this window closes.
pause
exit /b %inventory_scan_exit%
