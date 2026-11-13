param([string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe")

# Builds the headless sidecar engine (dist\engine\agnostos-engine.exe) and copies it to
# the Tauri externalBin slot (app\src-tauri\binaries\agnostos-engine-x86_64-pc-windows-msvc.exe).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $Python)) {
    # Other machines/CI: fall back to the python on PATH (or pass -Python explicitly).
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) { throw "Python not found: $Python" }
    $Python = $found.Source
}
& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --quiet "pyinstaller>=6.10"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed to install" }
}
& $Python -c "import openpyxl, pdfplumber, docx, dotenv, openai, ruamel.yaml, ddgs, truststore, certifi, tzdata, httpx, googleapiclient, google_auth_oauthlib" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --quiet -r requirements.txt google-api-python-client google-auth-oauthlib
    if ($LASTEXITCODE -ne 0) { throw "Engine dependencies failed to install" }
}

$ErrorActionPreference = "Continue"
& $Python -m PyInstaller --noconfirm --clean --distpath dist\engine --workpath build\engine-pyi `
    desktop_engine\agnostos-engine.spec 2>&1 | ForEach-Object { "$_" }
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0) { throw "Engine build failed" }

$exe = "dist\engine\agnostos-engine.exe"
if (-not (Test-Path $exe -PathType Leaf)) { throw "Missing $exe" }

$ErrorActionPreference = "Continue"
$probe = '{"id":1,"method":"ping","params":{}}' | & $exe 2>$null
$ErrorActionPreference = "Stop"
if ($LASTEXITCODE -ne 0 -or -not ($probe -match '"ok":true')) { throw "Engine smoke test failed: $probe" }

$target = "app\src-tauri\binaries\agnostos-engine-x86_64-pc-windows-msvc.exe"
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item $exe $target -Force
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "Built $exe ($size MB) and copied it to $target"
