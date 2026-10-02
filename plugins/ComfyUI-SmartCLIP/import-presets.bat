@echo off
rem ---------------------------------------------------------------------------
rem SmartCLIP prompt-library importer (double-click friendly)
rem
rem   show what the word list contains:
rem       import-presets.bat --list
rem
rem   import a ComfyUI workflow's prompt text as one category:
rem       import-presets.bat --file "D:\path\workflow.json" --family sd15 --role negative --category 经典2
rem
rem   preview without writing:
rem       import-presets.bat --file "mylib.json" --family sdxl --role positive --category 我的词库 --dry-run
rem
rem Needs the python that ComfyUI itself uses. Set SMARTCLIP_PYTHON to override.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
setlocal
set "PYTHONIOENCODING=utf-8"
set "PY=%SMARTCLIP_PYTHON%"
if "%PY%"=="" set "PY=C:\ComfyUI_windows_portable\python_embeded\python.exe"

if not exist "%PY%" (
    echo [SmartCLIP] python not found: %PY%
    echo            set SMARTCLIP_PYTHON to the ComfyUI python and run again
    pause
    exit /b 1
)

"%PY%" "%~dp0import_presets.py" %*
echo.
pause
