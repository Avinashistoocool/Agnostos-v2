param([string]$Python = "python")

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
& $Python -m pip install -r desktop-review-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies failed to install" }

$browsers = Join-Path $PSScriptRoot "build\desktop-review-browsers"
$env:PLAYWRIGHT_BROWSERS_PATH = $browsers
& $Python -m playwright install chromium --only-shell
if ($LASTEXITCODE -ne 0) { throw "Scraping browser failed to install" }
$shell = Get-ChildItem $browsers -Directory -Filter "chromium_headless_shell-*" |
    Select-Object -First 1
if (-not $shell) { throw "Chromium headless shell was not installed" }

& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name Agnostos-v2-Desktop --distpath dist --workpath build\desktop-review `
    --specpath build\desktop-review `
    --add-data "$($shell.FullName);playwright-browsers\$($shell.Name)" `
    --add-data "$PSScriptRoot\sources.yaml;." `
    --icon "$PSScriptRoot\docs\assets\agnostos.ico" `
    --add-data "$PSScriptRoot\docs\assets\agnostos.ico;assets" `
    --add-data "$PSScriptRoot\docs\assets\agnostos-icon.png;assets" `
    --add-data "$PSScriptRoot\docs\assets\agnostos-banner.png;assets" `
    --add-data "$PSScriptRoot\LICENSE;licenses" `
    --add-data "$PSScriptRoot\docs\licenses;licenses" `
    --collect-submodules outreach --collect-submodules openpyxl `
    --collect-submodules ddgs `
    --collect-all playwright --collect-all tzdata `
    --collect-all googleapiclient --collect-submodules google_auth_oauthlib `
    --exclude-module PySide6.QtWebEngineWidgets --exclude-module PySide6.QtWebEngineCore `
    desktop_review\launcher.py
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }

$folder = "dist\Agnostos-v2-Desktop"
foreach ($file in "Agnostos-v2-Desktop.exe", "_internal\sources.yaml") {
    if (-not (Test-Path "$folder\$file" -PathType Leaf)) { throw "Missing desktop asset: $file" }
}
$private = Get-ChildItem $folder -Recurse -File | Where-Object {
    $_.Name -eq ".env" -or $_.Name -like "*.env" -or
    $_.Name -eq ".app_secret" -or $_.Name -like "*.db" -or
    $_.Name -like "*.xlsx" -or $_.Name -eq "reply_queue.json" -or
    $_.Name -eq "conversations.html" -or $_.Name -eq "credentials.json"
}
if ($private) { throw "Private files found in desktop distribution: $($private.FullName -join ', ')" }
Compress-Archive -Path $folder -DestinationPath "dist\Agnostos-v2-Desktop.zip" -Force
Write-Host "Built dist\Agnostos-v2-Desktop.zip and dist\Agnostos-v2-Desktop\Agnostos-v2-Desktop.exe"
