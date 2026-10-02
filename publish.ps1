# Turn this folder into a git repository and (optionally) push it to GitHub.
#
#   powershell -ExecutionPolicy Bypass -File publish.ps1 -User YOUR_GITHUB_USER
#   powershell -ExecutionPolicy Bypass -File publish.ps1 -User YOUR_GITHUB_USER -Push
#   powershell -ExecutionPolicy Bypass -File publish.ps1 -User someone -Repo my-nodes -Branch main
#
# Without -Push it only does local work: git init / add / commit / branch / remote add,
# and prints the exact commands left to run. Nothing is uploaded.
#
# ASCII only on purpose (Windows PowerShell 5.1 reads .ps1 as ANSI/GBK without a BOM).

param(
    [string]$User = '',
    [string]$Repo = 'ComfyUI-Model-Conflict-and-Prompt-Tools',
    [string]$Branch = 'main',
    [string]$Message = '',
    [string]$AuthorName = 'ComfyUI-Model-Conflict-and-Prompt-Tools',
    [string]$AuthorEmail = 'ComfyUI-Model-Conflict-and-Prompt-Tools@users.noreply.github.com',
    [switch]$Push
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Invoke-Git([string[]]$GitArgs) {
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed (exit $LASTEXITCODE)" }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git not found in PATH" }

# ---------------------------------------------------------------- init
# (init first: a repo-local identity can only be set inside a repository)
if (-not (Test-Path (Join-Path $PSScriptRoot '.git'))) {
    Invoke-Git @('init')
    Write-Output "initialised a new repository"
} else {
    Write-Output "repository already initialised"
}

# ---------------------------------------------------------------- identity
# A commit needs user.name / user.email. Use the global ones when they exist;
# otherwise set a local identity for THIS repo only.
$globalName  = (& git config --global user.name)  2>$null
$globalEmail = (& git config --global user.email) 2>$null
if (-not $globalName -or -not $globalEmail) {
    Write-Output "no global git identity - setting a local one for this repo:"
    Write-Output "  user.name  = $AuthorName"
    Write-Output "  user.email = $AuthorEmail"
    Write-Output "  (change it later: git config user.name ... / git config user.email ... )"
    Invoke-Git @('config', 'user.name',  $AuthorName)
    Invoke-Git @('config', 'user.email', $AuthorEmail)
}

Invoke-Git @('add', '-A')

$staged = (& git diff --cached --name-only) 2>$null
if (-not $staged) {
    Write-Output "nothing staged - no commit made"
} else {
    if (-not $Message) {
        $Message = "ComfyUI plugins: SmartCLIP, ModelImagePicker, AutoSavePreview (+ tools)"
    }
    Invoke-Git @('commit', '-m', $Message)
    Write-Output "committed $((@($staged)).Count) path(s)"
}

Invoke-Git @('branch', '-M', $Branch)

# ---------------------------------------------------------------- remote
if ($User) {
    $url = "https://github.com/$User/$Repo.git"
    $existing = (& git remote) 2>$null
    if ($existing -contains 'origin') {
        Invoke-Git @('remote', 'set-url', 'origin', $url)
        Write-Output "origin -> $url"
    } else {
        Invoke-Git @('remote', 'add', 'origin', $url)
        Write-Output "origin added -> $url"
    }
} else {
    Write-Output "no -User given: skipping the remote. Add it later with:"
    Write-Output "  git remote add origin https://github.com/YOUR_GITHUB_USER/$Repo.git"
}

Write-Output ""
Write-Output "--------------------------------------------------------------"
Write-Output "Next steps"
Write-Output "--------------------------------------------------------------"
if ($User) {
    Write-Output "1) create the EMPTY repo on GitHub (do NOT let it add a README):"
    Write-Output "     https://github.com/new?name=$Repo"
    Write-Output "   or with the GitHub CLI:"
    Write-Output "     gh repo create $User/$Repo --public --source=. --remote=origin"
    Write-Output ""
    Write-Output "2) push:"
    Write-Output "     git push -u origin $Branch"
} else {
    Write-Output "  git remote add origin https://github.com/YOUR_GITHUB_USER/$Repo.git"
    Write-Output "  git push -u origin $Branch"
}

if ($Push) {
    Write-Output ""
    Write-Output "pushing..."
    Invoke-Git @('push', '-u', 'origin', $Branch)
    Write-Output "pushed to origin/$Branch"
}
