# Build LuminaCode desktop exe with PyInstaller.
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
# Optional: -Version 1.0.2  (overrides the version read from lumina/__init__.py)

param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

# ---- resolve version -------------------------------------------------------
if (-not $Version) {
    $Version = (Select-String -Path "lumina\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
}
Write-Host "==> Building LuminaCode v$Version" -ForegroundColor Cyan

# ---- ensure deps -----------------------------------------------------------
Write-Host "==> Installing build dependencies" -ForegroundColor Cyan
python -m pip install --quiet pyinstaller pywebview
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# ---- run tests -------------------------------------------------------------
Write-Host "==> Running tests" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

# ---- clean stale outputs ----------------------------------------------------
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
Remove-Item -Force "LuminaCode.spec" -ErrorAction SilentlyContinue

# ---- build exe --------------------------------------------------------------
Write-Host "==> PyInstaller onefile build" -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name LuminaCode `
    --icon assets\icon.ico `
    --add-data "assets\icon.ico;assets" `
    --add-data "lumina\web\static;lumina\web\static" `
    --hidden-import webview.platforms.winforms `
    --hidden-import webview.platforms.win32 `
    --hidden-import webview.platforms.edgechromium `
    --hidden-import webview.platforms.mshtml `
    --exclude-module PyQt5 `
    --exclude-module PyQt6 `
    --exclude-module matplotlib `
    --exclude-module PIL `
    --exclude-module tkinter `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# ---- smoke test --------------------------------------------------------------
$Exe = Join-Path $Root "dist\LuminaCode.exe"
if (-not (Test-Path $Exe)) { throw "build output missing: $Exe" }
$Info = Get-Item $Exe
Write-Host "==> Built: $($Info.FullName) ($([math]::Round($Info.Length / 1MB, 1)) MB)" -ForegroundColor Green

Write-Host "==> Launching smoke test (server on 127.0.0.1:1200)" -ForegroundColor Cyan
$proc = Start-Process -FilePath $Exe -PassThru
$ok = $false
try {
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:1200/" -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -eq 200 -and $resp.Content -match "LuminaCode") {
                $ok = $true
                break
            }
        } catch {
            # server not up yet; keep waiting
        }
    }
    if (-not $ok) { throw "smoke test: server did not respond on 127.0.0.1:1200" }
    Write-Host "==> Smoke test OK (HTTP $($resp.StatusCode), page contains 'LuminaCode')" -ForegroundColor Green
}
finally {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
}

Write-Host "==> Done. Upload $Exe to the v$Version GitHub release." -ForegroundColor Green
