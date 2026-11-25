# Creates desktop shortcuts: Griga CLI and Griga Docs (Obsidian vault).
# ASCII-only on purpose: Windows PowerShell 5 reads .ps1 as ANSI.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell

# --- Griga CLI ---------------------------------------------------------
$shortcutPath = Join-Path $desktop 'Griga CLI.lnk'
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $root 'interfaces\start-cli.ps1') + '"'
$shortcut.WorkingDirectory = $root
$shortcut.Description = 'Griga AGI v0.1 - interactive graph CLI'
$pythonIcon = Join-Path $root '.venv\Scripts\python.exe'
if (Test-Path $pythonIcon) {
    $shortcut.IconLocation = $pythonIcon + ',0'
}
$shortcut.Save()
Write-Host "Shortcut: $shortcutPath"

# --- Griga Docs (Obsidian vault) --------------------------------------
$docs = Join-Path $root 'docs'
if (Test-Path $docs) {
    $encoded = [uri]::EscapeDataString($docs)
    $urlPath = Join-Path $desktop 'Griga Docs.url'
    $content = "[InternetShortcut]`r`nURL=obsidian://open?path=$encoded`r`nIconFile=$env:SystemRoot\System32\shell32.dll`r`nIconIndex=70`r`n"
    Set-Content -Path $urlPath -Value $content -Encoding ASCII
    Write-Host "Shortcut: $urlPath"
}

Write-Host 'Done.'
