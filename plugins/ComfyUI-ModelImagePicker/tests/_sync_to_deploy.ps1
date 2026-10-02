# Copy the fixed source files to the deployed plugin directory and verify hashes.
$ErrorActionPreference = "Stop"

$src = "C:\ComfyUI-ModelConflict\src"
$dep = "C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_ModelImagePicker"
$files = @("model_preview_api.py", "web\js\model_image_picker.js")

$bad = 0
foreach ($f in $files) {
    Copy-Item (Join-Path $src $f) (Join-Path $dep $f) -Force
    $a = (Get-FileHash (Join-Path $src $f)).Hash
    $b = (Get-FileHash (Join-Path $dep $f)).Hash
    if ($a -ne $b) { Write-Host "MISMATCH $f"; $bad++ }
    else { Write-Host "ok  $f  $a  ($((Get-Item (Join-Path $dep $f)).Length) bytes)" }
}

# The interceptor's regression harness fetches the picker over HTTP; keep the
# repo's own copies of the other two JS files identical too (they are unchanged
# by this fix, but a drift here has bitten us before).
foreach ($f in @("web\js\model_conflict.js")) {
    $a = (Get-FileHash (Join-Path $src $f)).Hash
    $b = (Get-FileHash (Join-Path $dep $f)).Hash
    Write-Host "$(if ($a -eq $b) { 'ok ' } else { 'DIFF' }) $f  src=$a dep=$b"
}

if ($bad) { throw "$bad file(s) failed to sync" }
Write-Host "SYNC OK"
