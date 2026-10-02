# Start a SECOND ComfyUI on port 8189 for verification only.
# The user's instance (8188) is never touched: no kill, no restart, no config change.
$ErrorActionPreference = "Stop"

$root  = "C:\ComfyUI_windows_portable"
$py    = "$root\python_embeded\python.exe"
$cwd   = "$root\ComfyUI"
$log   = "C:\ComfyUI-ModelConflict\tests\_8189_comfyui.log"
$errlog= "C:\ComfyUI-ModelConflict\tests\_8189_comfyui.err.log"

Remove-Item $log, $errlog -ErrorAction SilentlyContinue

$p = Start-Process -FilePath $py `
    -ArgumentList @("-s", "main.py", "--port", "8189", "--cpu") `
    -WorkingDirectory $cwd `
    -RedirectStandardOutput $log -RedirectStandardError $errlog `
    -PassThru

"pid=$($p.Id)" | Set-Content "C:\ComfyUI-ModelConflict\tests\_8189.pid"
Write-Host "started pid=$($p.Id), log=$log"
