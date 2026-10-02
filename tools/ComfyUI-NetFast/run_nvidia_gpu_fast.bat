@echo off
rem ============================================================
rem  ComfyUI launcher with China-friendly network settings
rem
rem  Additive on purpose: it does not modify run_nvidia_gpu.bat.
rem  Start ComfyUI with this file and the Manager / pip / Hugging
rem  Face traffic gets the settings below; start the original file
rem  and nothing changes.
rem
rem  ASCII only: the Chinese walkthrough lives in the README next
rem  to this file (echo of non-ASCII text garbles on a GBK console).
rem ============================================================

setlocal

rem ---- mirrors (work without any proxy) ----------------------
set "HF_ENDPOINT=https://hf-mirror.com"
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
set "UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"

rem never send localhost calls through a proxy
set "NO_PROXY=127.0.0.1,localhost,::1"
set "no_proxy=127.0.0.1,localhost,::1"

rem ---- optional proxy ----------------------------------------
rem Port of your FlClash / Clash "mixed" listener. Override it
rem without editing this file:  set PROXY_PORT=7897  before running.
if not defined PROXY_PORT set "PROXY_PORT=7890"

rem Fallback GitHub prefix used only when no proxy is listening.
if not defined GH_MIRROR set "GH_MIRROR=https://ghfast.top/https://github.com"

netstat -an | findstr /C:"127.0.0.1:%PROXY_PORT%" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    set "HTTP_PROXY=http://127.0.0.1:%PROXY_PORT%"
    set "HTTPS_PROXY=http://127.0.0.1:%PROXY_PORT%"
    set "ALL_PROXY=http://127.0.0.1:%PROXY_PORT%"
    set "http_proxy=http://127.0.0.1:%PROXY_PORT%"
    set "https_proxy=http://127.0.0.1:%PROXY_PORT%"
    set "GITHUB_ENDPOINT="
    echo [netfast] proxy ON  -^> 127.0.0.1:%PROXY_PORT% ^(python/git/pip all use it^)
) else (
    set "GITHUB_ENDPOINT=%GH_MIRROR%"
    echo [netfast] proxy OFF -^> git clone via %GH_MIRROR%
)
echo [netfast] HF_ENDPOINT   = %HF_ENDPOINT%
echo [netfast] PIP_INDEX_URL = %PIP_INDEX_URL%
echo.

if defined COMFY_NETFAST_DRYRUN (
    echo [netfast] COMFY_NETFAST_DRYRUN is set - environment only, ComfyUI not started.
    endlocal
    exit /b 0
)

cd /d "%~dp0"
call run_nvidia_gpu.bat
endlocal
