param([string]$Python = "python")

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
& $Python -m pip install -r desktop-review-requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Desktop dependencies failed to install" }

$web = Join-Path $PSScriptRoot "desktop_review\web"
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name Agnostos-v2-Review --distpath dist --workpath build\desktop-review `
    --specpath build\desktop-review `
    --add-data "$web\index.html;desktop_review\web" `
    --add-data "$web\app.css;desktop_review\web" `
    --add-data "$web\app.js;desktop_review\web" `
    --collect-submodules openpyxl --collect-submodules webview `
    desktop_review\launcher.py
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }

$folder = "dist\Agnostos-v2-Review"
foreach ($file in "Agnostos-v2-Review.exe", "_internal\desktop_review\web\index.html",
        "_internal\desktop_review\web\app.css", "_internal\desktop_review\web\app.js") {
    if (-not (Test-Path "$folder\$file" -PathType Leaf)) { throw "Missing desktop asset: $file" }
}
$private = Get-ChildItem $folder -Recurse -File | Where-Object {
    $_.Name -eq ".env" -or $_.Name -like "*.env" -or
    $_.Name -eq ".app_secret" -or $_.Name -like "*.db" -or
    $_.Name -like "*.xlsx" -or $_.Name -eq "reply_queue.json" -or
    $_.Name -eq "conversations.html" -or $_.Name -eq "credentials.json"
}
if ($private) { throw "Private files found in desktop distribution: $($private.FullName -join ', ')" }
Compress-Archive -Path $folder -DestinationPath "dist\Agnostos-v2-Review.zip" -Force
Write-Host "Built dist\Agnostos-v2-Review.zip and dist\Agnostos-v2-Review\Agnostos-v2-Review.exe"
