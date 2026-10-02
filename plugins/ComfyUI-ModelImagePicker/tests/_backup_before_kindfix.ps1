# Back up the two files this fix touches, BEFORE editing them.
# Source repo: C:\ComfyUI-ModelConflict\src
# Deployed  : <ComfyUI>\custom_nodes\ComfyUI_ModelImagePicker
$ErrorActionPreference = "Stop"

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$src   = "C:\ComfyUI-ModelConflict\src"
$dep   = "C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_ModelImagePicker"
$out   = "C:\ComfyUI_windows_portable\ComfyUI\_plugin_backups\${stamp}_before_kindfix"

New-Item -ItemType Directory -Force -Path "$out\src" | Out-Null
New-Item -ItemType Directory -Force -Path "$out\deployed" | Out-Null

$files = @("model_preview_api.py", "web\js\model_image_picker.js")

foreach ($f in $files) {
    Copy-Item (Join-Path $src $f) (Join-Path "$out\src"  (Split-Path $f -Leaf)) -Force
    Copy-Item (Join-Path $dep $f) (Join-Path "$out\deployed" (Split-Path $f -Leaf)) -Force
}

# Verify every backup is byte-identical to its original.
$bad = 0
foreach ($f in $files) {
    $leaf = Split-Path $f -Leaf
    foreach ($pair in @(@($src, "src"), @($dep, "deployed"))) {
        $a = (Get-FileHash (Join-Path $pair[0] $f)).Hash
        $b = (Get-FileHash (Join-Path "$out\$($pair[1])" $leaf)).Hash
        if ($a -ne $b) { Write-Host "MISMATCH $($pair[1])\$leaf"; $bad++ }
        else { Write-Host "ok  $($pair[1])\$leaf  $a" }
    }
}

Write-Host "backup dir: $out"
if ($bad) { throw "$bad backup file(s) did not verify" }
Write-Host "BACKUP OK"
