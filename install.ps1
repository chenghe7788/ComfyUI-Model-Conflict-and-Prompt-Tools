# Install the plugins in this repo into a ComfyUI install.
#
#   powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -ComfyUI "D:\ComfyUI_windows_portable\ComfyUI"
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Only ComfyUI-SmartCLIP
#
# What it does, per plugin:
#   * backs up the existing target folder to <ComfyUI>\_plugin_backups\<stamp>_<name>
#   * copies the plugin files (skipping tests\, docs\, __pycache__ and *.bak-*)
#   * KEEPS an existing prompt_presets\presets.json unless -ForcePresets is given
#
# Nothing outside <ComfyUI> is touched. Uninstall = delete the target folder.
#
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI/GBK unless the
# file has a UTF-8 BOM, which silently corrupts non-ASCII source.

param(
    [string]$ComfyUI = '',
    [switch]$DryRun,
    [switch]$ForcePresets,
    [string[]]$Only = @()
)

$ErrorActionPreference = 'Stop'

$repoRoot = $PSScriptRoot

$plugins = @(
    @{ name = 'ComfyUI-SmartCLIP';        dir = 'ComfyUI_SmartCLIP' }
    @{ name = 'ComfyUI-ModelImagePicker'; dir = 'ComfyUI_ModelImagePicker' }
    @{ name = 'ComfyUI-AutoSavePreview';  dir = 'ComfyUI_AutoSavePreview' }
)

$skipDirs  = @('tests', 'docs', '__pycache__', 'node_modules', '.git')
$skipFiles = @('*.pyc', '*.bak-*', '*.bak', '*.bak.json')
# the prompt word list is user data: handled separately, never copied over silently
$presetRel = 'prompt_presets\presets.json'
$skipRel   = @($presetRel)

# ---------------------------------------------------------------- locate ComfyUI
function Test-ComfyRoot([string]$p) {
    if (-not $p) { return $false }
    if (-not (Test-Path $p)) { return $false }
    return (Test-Path (Join-Path $p 'custom_nodes'))
}

if ($ComfyUI) {
    if (-not (Test-ComfyRoot $ComfyUI)) {
        # allow the portable root instead of the inner ComfyUI folder
        $inner = Join-Path $ComfyUI 'ComfyUI'
        if (Test-ComfyRoot $inner) { $ComfyUI = $inner }
        else { throw "no custom_nodes folder under: $ComfyUI" }
    }
} else {
    $candidates = New-Object System.Collections.ArrayList
    if ($env:COMFYUI_ROOT) { [void]$candidates.Add($env:COMFYUI_ROOT) }
    foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null })) {
        $r = "$($d.Name):\"
        [void]$candidates.Add((Join-Path $r 'ComfyUI_windows_portable\ComfyUI'))
        [void]$candidates.Add((Join-Path $r 'ComfyUI\ComfyUI'))
        [void]$candidates.Add((Join-Path $r 'ComfyUI'))
    }
    if ($env:USERPROFILE) {
        [void]$candidates.Add((Join-Path $env:USERPROFILE 'ComfyUI_windows_portable\ComfyUI'))
        [void]$candidates.Add((Join-Path $env:USERPROFILE 'ComfyUI\ComfyUI'))
    }
    foreach ($c in $candidates) { if (Test-ComfyRoot $c) { $ComfyUI = $c; break } }

    if (-not $ComfyUI) {
        # one level deeper under each drive root, e.g. D:\somewhere\ComfyUI_windows_portable\ComfyUI
        foreach ($d in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -ne $null })) {
            $r = "$($d.Name):\"
            $hits = @(Get-ChildItem $r -Directory -ErrorAction SilentlyContinue |
                      Where-Object { $_.Name -like '*ComfyUI*' })
            foreach ($h in $hits) {
                foreach ($sub in @($h.FullName, (Join-Path $h.FullName 'ComfyUI'))) {
                    if (Test-ComfyRoot $sub) { $ComfyUI = $sub; break }
                }
                if ($ComfyUI) { break }
            }
            if ($ComfyUI) { break }
        }
    }

    if (-not $ComfyUI) {
        throw "could not find ComfyUI. Pass it explicitly: -ComfyUI <path to the folder that contains custom_nodes>"
    }
}

$customNodes = Join-Path $ComfyUI 'custom_nodes'
$backupRoot  = Join-Path $ComfyUI '_plugin_backups'
$stamp       = Get-Date -Format 'yyyyMMdd-HHmmss'

Write-Output "ComfyUI   : $ComfyUI"
Write-Output "custom_nodes: $customNodes"
Write-Output ""

# ---------------------------------------------------------------- copy helpers
# $Rel is the path relative to the plugin root, used to skip the user word list.
function Copy-PluginFiles([string]$Src, [string]$Dst, [string]$Rel, [switch]$IsDryRun) {
    Get-ChildItem $Src -Force | ForEach-Object {
        $name = $_.Name
        $relChild = if ($Rel) { Join-Path $Rel $name } else { $name }
        if ($_.PSIsContainer) {
            if ($skipDirs -contains $name) { return }
            $sub = Join-Path $Dst $name
            if (-not $IsDryRun) { New-Item -ItemType Directory -Force -Path $sub | Out-Null }
            Copy-PluginFiles $_.FullName $sub $relChild -IsDryRun:$IsDryRun
        } else {
            if ($skipRel -contains $relChild) { return }
            $skip = $false
            foreach ($pat in $skipFiles) { if ($name -like $pat) { $skip = $true } }
            if ($skip) { return }
            $target = Join-Path $Dst $name
            if (-not $IsDryRun) { Copy-Item $_.FullName $target -Force }
        }
    }
}

# ---------------------------------------------------------------- install loop
$installed = 0
foreach ($p in $plugins) {
    if ($Only.Count -gt 0 -and ($Only -notcontains $p.name) -and ($Only -notcontains $p.dir)) { continue }

    $src = Join-Path (Join-Path $repoRoot 'plugins') $p.name
    $dst = Join-Path $customNodes $p.dir

    if (-not (Test-Path $src)) { Write-Output "SKIP  $($p.name): source not found ($src)"; continue }

    Write-Output "== $($p.name)  ->  $dst"

    if (Test-Path $dst) {
        $bak = Join-Path $backupRoot ("{0}_{1}" -f $stamp, $p.name)
        if ($DryRun) {
            Write-Output "   would back up existing folder to $bak"
        } else {
            New-Item -ItemType Directory -Force -Path $bak | Out-Null
            Copy-Item (Join-Path $dst '*') $bak -Recurse -Force -ErrorAction SilentlyContinue
            Write-Output "   backed up existing folder to $bak"
        }
    }

    # the word list is user data: never overwrite it silently
    $presetDst = Join-Path $dst $presetRel
    $presetSrc = Join-Path $src $presetRel
    $keepPresets = (Test-Path $presetDst) -and (-not $ForcePresets)

    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $dst | Out-Null }
    Copy-PluginFiles $src $dst '' -IsDryRun:$DryRun

    if (Test-Path $presetSrc) {
        if ($keepPresets) {
            Write-Output "   kept existing prompt_presets\presets.json"
        } elseif ($DryRun) {
            Write-Output "   would write prompt_presets\presets.json from the repo"
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path $presetDst) | Out-Null
            Copy-Item $presetSrc $presetDst -Force
            Write-Output "   wrote prompt_presets\presets.json from the repo"
        }
    }

    # drop stale bytecode so a removed/renamed module cannot be imported again
    if (-not $DryRun) {
        Get-ChildItem -Path $dst -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }

    $installed++
}

Write-Output ""
if ($DryRun) {
    Write-Output "DRYRUN complete - nothing was written. $installed plugin(s) planned."
} else {
    Write-Output "Installed $installed plugin(s)."
    Write-Output "RESTART ComfyUI. After that, frontend-only JS changes just need Ctrl+Shift+R."
    if (Test-Path $backupRoot) { Write-Output "Old versions (if any) are under: $backupRoot" }
}
