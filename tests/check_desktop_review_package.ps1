$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$folder = Join-Path (Get-Location) "dist\Agnostos-v2-Desktop"
$exe = Join-Path $folder "Agnostos-v2-Desktop.exe"
$archive = Join-Path (Get-Location) "dist\Agnostos-v2-Desktop.zip"
$required = @(
    "Agnostos-v2-Desktop.exe",
    "_internal\sources.yaml",
    "_internal\licenses\LICENSE",
    "_internal\licenses\THIRD_PARTY_NOTICES.md",
    "_internal\licenses\LGPL-3.0.txt",
    "_internal\licenses\GPL-3.0.txt"
)
foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $folder $file) -PathType Leaf)) {
        throw "Missing desktop package file: $file"
    }
}
$private = Get-ChildItem $folder -Recurse -File | Where-Object {
    $_.Name -eq ".env" -or $_.Name -like "*.env" -or
    $_.Name -eq ".app_secret" -or $_.Name -like "*.db" -or
    $_.Name -like "*.xlsx" -or $_.Name -eq "reply_queue.json" -or
    $_.Name -eq "conversations.html" -or $_.Name -eq "credentials.json" -or
    $_.Extension -in @(".pdf", ".eml") -or
    ($_.Extension -eq ".docx" -and $_.FullName -notlike "*\_internal\docx\templates\default.docx")
}
if ($private) { throw "Private file embedded in distribution: $($private.FullName -join ', ')" }
if (Test-Path "$folder\_internal\desktop_review\web") {
    throw "Old HTTP/WebView frontend must not be bundled in the native executable"
}
$chromium = @(Get-ChildItem "$folder\_internal\playwright-browsers" -Recurse -File |
    Where-Object { $_.Name -eq "chrome-headless-shell.exe" })
if ($chromium.Count -ne 1) { throw "Packaged Chromium headless shell is missing" }
if (Test-Path "$folder\_internal\playwright-browsers\.links") {
    throw "Playwright cache link reveals the build machine's local path"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($archive)
try {
    $files = @($zip.Entries | ForEach-Object { $_.FullName.Replace("\", "/") })
    foreach ($file in $required) {
        $inside = "Agnostos-v2-Desktop/" + $file.Replace("\", "/")
        if ($inside -notin $files) { throw "Missing ZIP entry: $inside" }
    }
    if ($files | Where-Object {
        $_ -match "(?i)(^|/)(\.env|\.app_secret|reply_queue\.json|conversations\.html|credentials\.json)$" -or
        ($_ -match "(?i)\.(db|xlsx|pdf|eml)$" -or
         ($_ -match "(?i)\.docx$" -and
          $_ -notmatch "(?i)/_internal/docx/templates/default\.docx$"))
    }) { throw "Private file embedded in ZIP" }
} finally {
    $zip.Dispose()
}

$data = Join-Path (Get-Location) "build\native-package-test-data"
$previous = $env:LOCALAPPDATA
try {
    $env:LOCALAPPDATA = $data
    $process = Start-Process -FilePath $exe -ArgumentList "--health-check" -PassThru
    if (-not $process.WaitForExit(45000)) {
        Stop-Process -Id $process.Id
        throw "Packaged desktop health check timed out"
    }
    if ($process.ExitCode -ne 0) { throw "Packaged health exit code: $($process.ExitCode)" }
    if (-not (Test-Path (Join-Path $data "Agnostos-v2-Review") -PathType Container)) {
        throw "Per-user app settings directory not created"
    }
    if (Test-Path (Join-Path $data "Agnostos-v2-Review\agnostos.db")) {
        throw "Viewer created a database instead of using the v2 workspace"
    }
    python tests\packaged_cli_smoke.py $exe
    if ($LASTEXITCODE -ne 0) { throw "Frozen CLI fixture smoke test failed" }
    Write-Host "Packaged launcher, assets, ZIP and private-data audit passed."
} finally {
    $env:LOCALAPPDATA = $previous
    if (Test-Path $data) { Remove-Item $data -Recurse -Force }
}
