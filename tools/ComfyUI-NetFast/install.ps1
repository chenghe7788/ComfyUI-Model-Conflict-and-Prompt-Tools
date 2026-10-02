# Deploy / revert the ComfyUI network-speedup settings.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Restore
#
# Changes made (all local to this ComfyUI install, nothing global):
#   1. python_embeded\pip.ini                 -> PyPI mirror for this Python only
#   2. run_nvidia_gpu_fast.bat                -> new launcher (never overwrites the stock one)
#   3. user\__manager\config.ini              -> use_uv = True (backed up first)

param(
    [string]$ComfyRoot = 'C:\ComfyUI_windows_portable',
    [switch]$Restore,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$src      = Join-Path $PSScriptRoot 'src'
$python   = Join-Path $ComfyRoot 'python_embeded\python.exe'
$pipIni   = Join-Path $ComfyRoot 'python_embeded\pip.ini'
$launcher = Join-Path $ComfyRoot 'run_nvidia_gpu_fast.bat'
$cfg      = Join-Path $ComfyRoot 'ComfyUI\user\__manager\config.ini'
$stamp    = Get-Date -Format 'yyyyMMdd-HHmmss'

if (-not (Test-Path $python)) { throw "python_embeded not found under $ComfyRoot" }

if ($Restore) {
    foreach ($f in @($pipIni, $launcher)) {
        if (Test-Path $f) { Remove-Item $f -Force; Write-Output "removed $f" }
    }
    $backup = Get-ChildItem (Split-Path $cfg) -Filter 'config.ini.bak-*' -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($backup) {
        Copy-Item $backup.FullName $cfg -Force
        Write-Output "restored $cfg from $($backup.Name)"
    } else {
        Write-Output "no config.ini backup found; leaving $cfg untouched"
    }
    Write-Output "restart ComfyUI with the original launcher"
    return
}

# ---- plan only -------------------------------------------------------------
if ($DryRun) {
    Write-Output "DRYRUN - nothing is written. Target root: $ComfyRoot"
    Write-Output "  would write   $pipIni          (from src\pip.ini)"
    Write-Output "  would write   $launcher        (from src\run_nvidia_gpu_fast.bat)"
    if (Test-Path $cfg) {
        Write-Output "  would patch   $cfg  -> use_uv = True (backup: config.ini.bak-<stamp>)"
    } else {
        Write-Output "  config.ini not found (Manager never started?): $cfg"
    }
    return
}

# 1) pip mirror, scoped to this embedded Python (pip's "site" config)
Copy-Item (Join-Path $src 'pip.ini') $pipIni -Force
Write-Output "wrote $pipIni"

# 2) launcher wrapper
Copy-Item (Join-Path $src 'run_nvidia_gpu_fast.bat') $launcher -Force
Write-Output "wrote $launcher"

# 3) Manager: use uv for dependency installs (uv ships with this ComfyUI)
if (Test-Path $cfg) {
    Copy-Item $cfg "$cfg.bak-$stamp" -Force
    $lines = Get-Content $cfg
    $patched = $lines | ForEach-Object {
        if ($_ -match '^\s*use_uv\s*=') { 'use_uv = True' } else { $_ }
    }
    if (-not ($patched -match '^\s*use_uv\s*=')) {
        $patched = @($patched) + 'use_uv = True'
    }
    Set-Content -Path $cfg -Value $patched -Encoding ascii
    Write-Output "set use_uv = True in $cfg (backup: config.ini.bak-$stamp)"
} else {
    Write-Output "config.ini not found (Manager never started?): $cfg"
}

Write-Output ""
Write-Output "done. Start ComfyUI with: $launcher"
Write-Output "verify the launcher logic without starting ComfyUI:"
Write-Output "  set COMFY_NETFAST_DRYRUN=1 && `"$launcher`""
