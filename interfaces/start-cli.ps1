# Griga CLI launcher. ASCII-only: Windows PowerShell 5 reads this as ANSI.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $python = 'python'
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Host 'No .env found. Copy .env.example to .env and set PostgreSQL DSN.' -ForegroundColor Yellow
}

$env:PYTHONIOENCODING = 'utf-8'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Older console hosts may not allow changing the encoding.
}

$code = 0
try {
    & $python -m griga.interfaces.agent @args
    $code = $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $code = 1
}

if ($code -ne 0) {
    Read-Host 'Press Enter to close'
}
exit $code
