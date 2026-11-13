param([switch]$SkipEngine)

# Release build of the Tauri app (NSIS + MSI) with the frozen engine sidecar.
# Build-machine paths (user profile, cargo registry, checkout) are remapped so
# the shipped agnostos.exe does not reveal who built it or where.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $SkipEngine) {
    & "$PSScriptRoot\build-engine.ps1"
    if (-not $?) { throw "Engine build failed" }
}

$cargoHome = if ($env:CARGO_HOME) { $env:CARGO_HOME } else { Join-Path $env:USERPROFILE ".cargo" }
$rustupHome = if ($env:RUSTUP_HOME) { $env:RUSTUP_HOME } else { Join-Path $env:USERPROFILE ".rustup" }
$remap = @(
    "--remap-path-prefix=$PSScriptRoot=agnostos",
    "--remap-path-prefix=$cargoHome=cargo",
    "--remap-path-prefix=$rustupHome=rustup",
    "--remap-path-prefix=$env:USERPROFILE=home"
) -join " "
$env:RUSTFLAGS = (($env:RUSTFLAGS, $remap) | Where-Object { $_ }) -join " "

Set-Location app
# npm/cargo log progress on stderr, which "Stop" would treat as a failure.
$ErrorActionPreference = "Continue"
if (-not (Test-Path node_modules)) {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
}
npm run tauri build
if ($LASTEXITCODE -ne 0) { throw "Tauri build failed" }
$ErrorActionPreference = "Stop"

$exe = "src-tauri\target\release\agnostos.exe"
$bytes = [IO.File]::ReadAllBytes((Resolve-Path $exe))
$text = [Text.Encoding]::GetEncoding(28591).GetString($bytes)
$user = [regex]::Escape($env:USERPROFILE)
if ($text -match $user -or $text -match [regex]::Escape($PSScriptRoot)) {
    throw "$exe still contains a build-machine path"
}
Get-ChildItem src-tauri\target\release\bundle -Recurse -Include *.exe, *.msi |
    ForEach-Object { Write-Host ("Built {0} ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB)) }
