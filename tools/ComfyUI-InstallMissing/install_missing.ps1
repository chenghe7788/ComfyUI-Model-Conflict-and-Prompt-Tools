# Install the custom-node packs that the missing workflows need.
#
#   powershell -ExecutionPolicy Bypass -File install_missing.ps1 -DryRun       # plan only
#   powershell -ExecutionPolicy Bypass -File install_missing.ps1               # download + extract
#   powershell -ExecutionPolicy Bypass -File install_missing.ps1 -InstallDeps  # also pip install -r
#
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI/GBK unless the
# file has a UTF-8 BOM, which silently corrupts non-ASCII source.  The Chinese
# explanation lives in README.md instead.
#
# Downloads use Invoke-WebRequest, the same path that already worked for the
# mirror probes.  The pack list was verified against the ZHO workflows' own
# README and against ComfyUI-3D-Pack's upstream source, NOT guessed from the
# Manager DB (which maps some of these node types to unrelated forks).

param(
    [string]$ComfyUI = 'C:\ComfyUI_windows_portable\ComfyUI',
    [switch]$DryRun,
    [switch]$InstallDeps
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'      # the progress bar makes IWR much slower

$customNodes = Join-Path $ComfyUI 'custom_nodes'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logDir = Join-Path $PSScriptRoot ("log-" + $stamp)
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$script:lastErr = ''

# Pack list: dir = folder under custom_nodes, repo = owner/name
$PACKS = @(
    @{ dir = 'ComfyUI-LivePortraitKJ';        repo = 'kijai/ComfyUI-LivePortraitKJ';              why = 'LivePortrait Animals workflow' }
    @{ dir = 'comfyui_controlnet_aux';        repo = 'Fannovel16/comfyui_controlnet_aux';         why = 'Stable Cascade Canny ControlNet workflow' }
    @{ dir = 'ComfyUI-BRIA_AI-RMBG';          repo = 'ZHO-ZHO-ZHO/ComfyUI-BRIA_AI-RMBG';          why = 'CRM Comfy 3D / Sketch to 3D workflows' }
    @{ dir = 'ComfyUI-Gemini';                repo = 'Visionatrix/ComfyUI-Gemini';                why = 'Ask_Gemini (the repo the Manager recommends)' }
    @{ dir = 'ComfyUI-Gemini-ZHO';            repo = 'ZHO-ZHO-ZHO/ComfyUI-Gemini';                why = 'ConcatText_Zho / DisplayText_Zho - the fork above does NOT contain them' }
    @{ dir = 'ComfyUI-Qwen';                  repo = 'SXQBW/ComfyUI-Qwen';                        why = 'SD3 Medium + Qwen2 workflow' }
    @{ dir = 'ComfyUI-VideoHelperSuite';      repo = 'Kosinkadink/ComfyUI-VideoHelperSuite';      why = 'VHS_LoadVideo / VHS_VideoCombine' }
    @{ dir = 'comfyui-portrait-master-zh-cn'; repo = 'ZHO-ZHO-ZHO/comfyui-portrait-master-zh-cn'; why = 'Portrait Master zh-cn workflow' }
    @{ dir = 'ComfyUI-ArtGallery';            repo = 'ZHO-ZHO-ZHO/ComfyUI-ArtGallery';            why = 'CosXL + ArtGallery (local copy is a broken clone)' }
    @{ dir = 'rgthree-comfy';                 repo = 'rgthree/rgthree-comfy';                     why = 'Any Switch / Fast Bypasser (rgthree)' }
    @{ dir = 'ComfyUI-Flowty-TripoSR-ZHO';    repo = 'ZHO-ZHO-ZHO/ComfyUI-Flowty-TripoSR-ZHO';    why = 'Sketch to 3D (*_Zho nodes)' }
)

function Get-GitHubZip {
    param([string]$Repo, [string]$OutFile)
    foreach ($branch in @('main', 'master')) {
        foreach ($prefix in @('https://github.com/', 'https://ghfast.top/https://github.com/')) {
            $url = "$prefix$Repo/archive/refs/heads/$branch.zip"
            try {
                Invoke-WebRequest -Uri $url -OutFile $OutFile -TimeoutSec 300 -UseBasicParsing
                if ((Get-Item $OutFile).Length -gt 1000) {
                    return @{ url = $url; branch = $branch }
                }
            } catch {
                $script:lastErr = $_.Exception.Message
            }
        }
    }
    return $null
}

$results = @()
foreach ($pack in $PACKS) {
    $target = Join-Path $customNodes $pack.dir
    $line = [ordered]@{
        pack = $pack.dir; repo = $pack.repo; action = ''; detail = ''
        has_requirements = $false; has_submodules = $false
    }

    if (Test-Path $target) {
        $items = Get-ChildItem $target -Force -ErrorAction SilentlyContinue
        $realFiles = @($items | Where-Object { $_.Name -ne '.git' })
        if ($realFiles.Count -gt 0) {
            $line.action = 'skip'
            $line.detail = 'folder already populated'
            $results += $line
            Write-Output ("[skip]    {0}  ({1})" -f $pack.dir, $line.detail)
            continue
        }
        $line.detail = 'folder existed but was empty / .git only - removed first'
        if (-not $DryRun) {
            try {
                Remove-Item $target -Recurse -Force -ErrorAction Stop
            } catch {
                # e.g. a stalled Manager git clone still holding .git/objects
                $line.action = 'blocked'
                $line.detail = "cannot remove existing folder: $($_.Exception.Message)"
                $results += $line
                Write-Output ("[BLOCKED] {0}  {1}" -f $pack.dir, $line.detail)
                continue
            }
        }
    }

    if ($DryRun) {
        $line.action = 'dry-run'
        $line.detail = "would download " + $pack.repo
        $results += $line
        Write-Output ("[dry-run] {0,-26} <- {1}   ({2})" -f $pack.dir, $pack.repo, $pack.why)
        continue
    }

    Write-Output ("[get]     {0}  <- {1}" -f $pack.dir, $pack.repo)
    $zip = Join-Path $logDir ($pack.dir + '.zip')
    $got = Get-GitHubZip -Repo $pack.repo -OutFile $zip
    if (-not $got) {
        $line.action = 'fail'
        $line.detail = "download failed: $script:lastErr"
        $results += $line
        Write-Output ("[FAIL]    {0}  {1}" -f $pack.dir, $line.detail)
        continue
    }

    $tmp = Join-Path $logDir ($pack.dir + '.unzip')
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $inner) {
        $line.action = 'fail'
        $line.detail = 'zip contained no directory'
        $results += $line
        continue
    }
    Move-Item $inner.FullName $target
    Remove-Item $tmp -Recurse -Force
    Remove-Item $zip -Force

    $line.action = 'installed'
    $line.detail = ("branch={0}, {1} files" -f $got.branch, (Get-ChildItem $target -Recurse -File).Count)
    $line.has_requirements = Test-Path (Join-Path $target 'requirements.txt')
    $line.has_submodules = Test-Path (Join-Path $target '.gitmodules')
    $results += $line
    Write-Output ("[ok]      {0}  {1}{2}{3}" -f $pack.dir, $line.detail,
        $(if ($line.has_requirements) { '  +requirements' } else { '' }),
        $(if ($line.has_submodules) { '  WARNING: repo has submodules, zip install is incomplete' } else { '' }))
}

# Move the workflow collection out of custom_nodes (it is not a node pack and
# makes ComfyUI log IMPORT FAILED on every start).
$notAPack = Join-Path $customNodes 'ComfyUI-Workflows-ZHO-main'
if (Test-Path $notAPack) {
    $moved = Join-Path (Split-Path $ComfyUI -Parent) '_moved_from_custom_nodes'
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force -Path $moved | Out-Null
        Move-Item $notAPack (Join-Path $moved 'ComfyUI-Workflows-ZHO-main') -Force -ErrorAction SilentlyContinue
    }
    Write-Output "[move]    ComfyUI-Workflows-ZHO-main -> _moved_from_custom_nodes (workflow collection, not a node pack)"
}

# Optional dependency install
if ($InstallDeps -and -not $DryRun) {
    $python = Join-Path (Split-Path $ComfyUI -Parent) 'python_embeded\python.exe'
    foreach ($pack in $PACKS) {
        $req = Join-Path (Join-Path $customNodes $pack.dir) 'requirements.txt'
        if (-not (Test-Path $req)) { continue }
        $text = Get-Content $req -Raw
        if ($text -match '(?im)^\s*(torch|torchvision|torchaudio)\b') {
            Write-Output ("[deps]    {0}: requirements mention torch - SKIPPED on purpose" -f $pack.dir)
            continue
        }
        Write-Output ("[deps]    {0}: pip install -r requirements.txt" -f $pack.dir)
        & $python -s -m pip install -r $req 2>&1 |
            Tee-Object -FilePath (Join-Path $logDir ($pack.dir + '.pip.log')) | Select-Object -Last 3
    }
}

Write-Output ''
Write-Output '================ summary ================'
foreach ($r in $results) {
    Write-Output ("  {0,-32} {1,-10} {2}" -f $r.pack, $r.action, $r.detail)
}
$needDeps = @($results | Where-Object { $_.has_requirements -and $_.action -eq 'installed' })
if ($needDeps.Count -gt 0) {
    Write-Output ''
    Write-Output 'packs shipping requirements.txt (dependency install still needed):'
    foreach ($r in $needDeps) { Write-Output ("  " + $r.pack) }
}
$results | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $logDir 'install_result.json') -Encoding utf8
Write-Output ''
Write-Output "logs: $logDir"
