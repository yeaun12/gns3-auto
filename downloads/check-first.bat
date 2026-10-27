@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (python prepare_virtualbox.py --check > check-result.txt 2>&1) else (py -3 prepare_virtualbox.py --check > check-result.txt 2>&1)
set "campus_check_exit=%errorlevel%"
type check-result.txt
echo.
echo Check output saved in check-result.txt
pause
exit /b %campus_check_exit%
