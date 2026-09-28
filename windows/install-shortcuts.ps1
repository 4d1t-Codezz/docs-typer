# Creates Start menu and desktop shortcuts for Docs Typer (and refreshes a taskbar pin if there is one).
# Run from PowerShell:  powershell -ExecutionPolicy Bypass -File windows\install-shortcuts.ps1

$repo = Split-Path -Parent $PSScriptRoot
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    Write-Error "Couldn't find pythonw. Install Python 3.10+ from python.org (tick 'Add python.exe to PATH')."
    exit 1
}

$targets = @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Docs Typer.lnk",
    "$([Environment]::GetFolderPath('Desktop'))\Docs Typer.lnk"
)
$pinned = "$env:APPDATA\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Docs Typer.lnk"
if (Test-Path $pinned) { $targets += $pinned }

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "-m docstyper"
    $lnk.WorkingDirectory = $repo
    $lnk.IconLocation = "$repo\assets\DocsTyper.ico,0"
    $lnk.Description = "Docs Typer"
    $lnk.Save()
    Write-Output "Wrote $path"
}
Write-Output "Done. To pin it: press Start, type Docs Typer, right-click it, and choose Pin to taskbar."
