# Stop ONLY the verification instance started by _start_8189.ps1.
# It refuses to kill anything unless the pid really owns port 8189.
# The user's own instance (8188) is never a candidate.
$ErrorActionPreference = "Stop"

$pidFile = "C:\ComfyUI-ModelConflict\tests\_8189.pid"
if (!(Test-Path $pidFile)) { throw "no pid file - nothing to stop" }
$target = [int]((Get-Content $pidFile | Select-Object -First 1) -replace "^pid=", "").Trim()

$owner = (Get-NetTCPConnection -State Listen -LocalPort 8189 -ErrorAction SilentlyContinue |
          Select-Object -First 1 -ExpandProperty OwningProcess)
if (-not $owner) { Write-Host "nothing is listening on 8189 (pid ${target} already gone)"; exit 0 }
if ($owner -ne $target) { throw "refusing to kill pid ${target}: port 8189 is owned by pid ${owner}" }
if ($target -eq 0) { throw "no usable pid" }

Stop-Process -Id $target -Force
Start-Sleep -Seconds 3
$still = Get-NetTCPConnection -State Listen -LocalPort 8189 -ErrorAction SilentlyContinue
Write-Host ("8189 listening after stop: " + [bool]$still)
Write-Host ("user instance 8188 still listening: " +
            [bool](Get-NetTCPConnection -State Listen -LocalPort 8188 -ErrorAction SilentlyContinue))
Remove-Item $pidFile -ErrorAction SilentlyContinue
