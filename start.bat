@echo off
rem Starts PostalPrint. Double-click this file or the desktop shortcut.
rem First run: creates the Python environment, installs dependencies and adds a desktop shortcut.
rem The file is kept ASCII-only because cmd.exe does not handle UTF-8 reliably.
setlocal
cd /d "%~dp0"
title PostalPrint

if not exist ".venv\Scripts\python.exe" (
    echo Foerste start: installerer programmet. Det tager et minuts tid...
    py -3 -m venv .venv >nul 2>nul
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    if not exist ".venv\Scripts\python.exe" goto :nopython
    powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'PostalPrint.lnk'));$s.TargetPath='%~dp0start.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.IconLocation='%SystemRoot%\System32\shell32.dll,16';$s.Save()" >nul 2>nul
)

rem (Re)install the program only when pyproject.toml has changed, e.g. after git pull
fc /b pyproject.toml ".venv\pyproject.installed" >nul 2>nul
if errorlevel 1 (
    echo Installerer/opdaterer programmets dele...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -e .
    if errorlevel 1 goto :installfailed
    copy /y pyproject.toml ".venv\pyproject.installed" >nul
)

".venv\Scripts\python.exe" -m postalprint %*
if errorlevel 1 pause
exit /b

:nopython
echo.
echo Python blev ikke fundet.
echo Installer Python 3.12 eller nyere fra https://www.python.org/downloads/
echo og saet hak i "Add python.exe to PATH" under installationen. Start derefter igen.
pause
exit /b 1

:installfailed
echo.
echo Installationen fejlede. Tjek internetforbindelsen og proev igen.
pause
exit /b 1
