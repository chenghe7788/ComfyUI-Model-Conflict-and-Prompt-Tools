@echo off
rem =====================================================================
rem  Install the Python dependencies of the newly added custom nodes.
rem
rem    install_deps.bat            install the safe set (recommended)
rem    install_deps.bat --full     also try the hard/compile-required ones
rem
rem  Run this on YOUR machine: the agent's sandbox proxy refuses pip's
rem  CONNECT tunnel (403), so dependencies can only be fetched here.
rem
rem  Deliberately NOT installed, because requirements.txt of those packs
rem  would downgrade shared libraries:
rem    LivePortraitKJ : numpy<=1.26.4      (would downgrade numpy)
rem    TripoSR-ZHO    : Pillow==10.1.0, transformers==4.35.0
rem    Qwen           : torch>=2.6         (would replace your torch)
rem  The minimal module list below was computed from the packs' own imports,
rem  so nothing here touches torch / numpy / Pillow versions.
rem =====================================================================

setlocal
set "PY=C:\ComfyUI_windows_portable\python_embeded\python.exe"
set "LOG=%~dp0deps-log-%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%-%TIME:~0,2%%TIME:~3,2%.txt"
set "LOG=%LOG: =0%"

if not exist "%PY%" (
    echo [deps] python not found: %PY%
    exit /b 1
)

rem ---- pip mirror: use the same reachable one as pip.ini -------------
set "PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/"
set "PIP_EXTRA_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.cloud.tencent.com/pypi/simple/"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "NO_PROXY=127.0.0.1,localhost,::1"

rem ---- optionally route through FlClash (same logic as run_nvidia_gpu_fast.bat)
if not defined PROXY_PORT set "PROXY_PORT=7890"
netstat -an | findstr /C:"127.0.0.1:%PROXY_PORT%" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    set "HTTP_PROXY=http://127.0.0.1:%PROXY_PORT%"
    set "HTTPS_PROXY=http://127.0.0.1:%PROXY_PORT%"
    echo [deps] proxy ON -^> 127.0.0.1:%PROXY_PORT%
) else (
    echo [deps] proxy OFF -^> using mirrors only
)

echo [deps] log file: %LOG%
echo.

rem ---- group 1: small, safe, no compiled parts ----------------------
echo === [1/3] Gemini / Qwen / TripoSR / VideoHelperSuite ===
"%PY%" -s -m pip install google-generativeai modelscope trimesh omegaconf einops rembg "imageio[ffmpeg]" imageio-ffmpeg >>"%LOG%" 2>&1
echo     exit=%errorlevel%   (details in the log)

rem ---- group 2: LivePortraitKJ runtime (wheels exist for win/amd64) --
echo === [2/3] LivePortraitKJ ===
"%PY%" -s -m pip install pykalman mediapipe onnxruntime-gpu numba insightface >>"%LOG%" 2>&1
echo     exit=%errorlevel%   (details in the log)

rem ---- group 3: needs a C++/CUDA toolchain, usually optional --------
if /i "%~1"=="--full" (
    echo === [3/3] torchmcubes (needs Visual Studio build tools + CUDA) ===
    "%PY%" -s -m pip install "git+https://github.com/tatsy/torchmcubes.git" >>"%LOG%" 2>&1
    echo     exit=%errorlevel%   (details in the log)
) else (
    echo === [3/3] skipped: torchmcubes ^(run with --full to try; needed only by the
    echo            Sketch to 3D workflow, and it must be compiled^)
)

echo.
echo =====================================================================
echo  Done. Now RESTART ComfyUI and check the result with:
echo    "%PY%" "%~dp0scan_missing.py"
echo  (that script prints which node types are still missing)
echo =====================================================================
endlocal
