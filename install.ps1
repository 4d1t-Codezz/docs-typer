# Installs Docs Typer on Windows. Paste this into PowerShell:
#   irm https://raw.githubusercontent.com/4d1t-Codezz/docs-typer/main/install.ps1 | iex
# It downloads the latest version into your user folder, gets a Python that works (if you don't
# have one), adds Docs Typer to the Start menu and desktop, and opens it. Run it again to update.
# "Install on Windows.bat" runs this from a downloaded copy instead.
#
# For testing: DOCSTYPER_REF picks the branch to download, DOCSTYPER_NO_OPEN=1 skips opening the
# app, and DOCSTYPER_OWN_PYTHON=1 installs Docs Typer's own Python even when one is already there.

function Install-DocsTyper {
    # Cmdlets stop on errors one by one: a global "Stop" would make Windows PowerShell treat uv's
    # progress output (on stderr) as a failure.
    $ProgressPreference = "SilentlyContinue"  # the progress bar makes downloads much slower
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $ref = if ($env:DOCSTYPER_REF) { $env:DOCSTYPER_REF } else { "main" }
    $home_dir = Join-Path $env:LOCALAPPDATA "Programs\Docs Typer"
    $app = Join-Path $home_dir "app"

    Write-Host "Installing Docs Typer..."
    Write-Host ""

    # Use the copy this script sits in, or download one when it's run straight from the web.
    $tmp = $null
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "docstyper\__init__.py"))) {
        $src = $PSScriptRoot
    } else {
        Write-Host "Downloading..."
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("docstyper-" + [Guid]::NewGuid())
        New-Item -ErrorAction Stop -ItemType Directory -Path $tmp | Out-Null
        $zip = Join-Path $tmp "docs-typer.zip"
        Invoke-WebRequest -ErrorAction Stop -UseBasicParsing -Uri "https://github.com/4d1t-Codezz/docs-typer/archive/refs/heads/$ref.zip" -OutFile $zip
        Expand-Archive -ErrorAction Stop -Path $zip -DestinationPath $tmp
        $src = (Get-ChildItem -Path $tmp -Directory | Select-Object -First 1).FullName
    }

    try {
        # Quit a running copy, so its files can be replaced.
        Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
            Where-Object { $_.CommandLine -like "*docstyper*" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 300

        if (Test-Path $app) { Remove-Item -ErrorAction Stop -Recurse -Force $app }
        New-Item -ErrorAction Stop -ItemType Directory -Path $app | Out-Null
        Copy-Item -ErrorAction Stop -Recurse (Join-Path $src "docstyper"), (Join-Path $src "assets") $app
        Get-ChildItem -Path $app -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
    } finally {
        if ($tmp) { Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    }

    # A usable Python is 3.10+ with Tk 8.6+. Prints its pythonw.exe (the windowless one).
    $check = "import sys, os, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6; print(os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'))"
    function Find-PythonW([string]$exe, [string[]]$pre = @()) {
        if (-not $exe -or -not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $null }
        try {
            $out = & $exe @pre -c $check 2>$null
            if ($LASTEXITCODE -eq 0 -and $out -and (Test-Path "$out".Trim())) { return "$out".Trim() }
        } catch { }
        return $null
    }

    # Docs Typer's own Python (from an earlier install) lives next to the app.
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $home_dir "python"
    $uv = Join-Path $home_dir "uv\uv.exe"
    $pythonw = $null
    if (Test-Path $uv) { $pythonw = Find-PythonW (& $uv python find 3.12 2>$null) }
    if (-not $pythonw -and -not $env:DOCSTYPER_OWN_PYTHON) {
        $pythonw = Find-PythonW "py" @("-3")
        if (-not $pythonw) { $pythonw = Find-PythonW "python" }
    }
    if (-not $pythonw) {
        # uv installs a Python just for Docs Typer, inside its folder (no admin, PATH unchanged).
        Write-Host "Getting a copy of Python for Docs Typer (about a minute)..."
        if (-not (Test-Path $uv)) {
            $env:UV_INSTALL_DIR = Join-Path $home_dir "uv"
            $env:UV_NO_MODIFY_PATH = "1"
            Invoke-RestMethod -ErrorAction Stop https://astral.sh/uv/install.ps1 | Invoke-Expression | Out-Null
            if (-not (Test-Path $uv)) { throw "Couldn't download uv (used to get Python). Check your internet connection and try again." }
        }
        $env:UV_PYTHON_INSTALL_BIN = "0"  # no python.exe in a bin folder off PATH, just a warning
        & $uv python install 3.12
        if ($LASTEXITCODE -ne 0) { throw "Couldn't download Python. Check your internet connection and try again." }
        $pythonw = Find-PythonW (& $uv python find 3.12)
        if (-not $pythonw) { throw "Python was installed but doesn't work. Please report this on GitHub." }
    }
    Write-Host "Using $pythonw"

    # Start menu and desktop shortcuts, plus the taskbar pin if there is one.
    $targets = @(
        (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Docs Typer.lnk"),
        (Join-Path ([Environment]::GetFolderPath("Desktop")) "Docs Typer.lnk")
    )
    $pinned = Join-Path $env:APPDATA "Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\Docs Typer.lnk"
    if (Test-Path $pinned) { $targets += $pinned }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($path in $targets) {
        $lnk = $shell.CreateShortcut($path)
        $lnk.TargetPath = $pythonw
        $lnk.Arguments = "-m docstyper"
        $lnk.WorkingDirectory = $app
        $lnk.IconLocation = (Join-Path $app "assets\DocsTyper.ico") + ",0"
        $lnk.Description = "Docs Typer"
        $lnk.Save()
    }

    Write-Host ""
    Write-Host "Done! Docs Typer is on your desktop and in the Start menu." -ForegroundColor Green
    Write-Host "To pin it to the taskbar: press Start, type Docs Typer, right-click it and choose Pin to taskbar."
    if (-not $env:DOCSTYPER_NO_OPEN) {
        Start-Process -FilePath $pythonw -ArgumentList "-m", "docstyper" -WorkingDirectory $app
    }
}

try {
    Install-DocsTyper
} catch {
    Write-Host ""
    Write-Host "Install failed: $($_.Exception.Message)" -ForegroundColor Red
    # Only exit when run as a file: exiting here would close the window of someone who pasted it.
    if ($PSCommandPath) { exit 1 }
}
