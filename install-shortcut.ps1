param(
    [string]$ExecutablePath = (Join-Path $PSScriptRoot 'dist\OPIc_Recorder.exe')
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
    throw "EXE not found: $ExecutablePath. Run build.bat first."
}
# The installed EXE and shortcut remain usable even while WSL is shut down.
$installDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\OPIcRecorder'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'Windows Desktop folder could not be resolved.' }
New-Item -ItemType Directory -Force -Path $installDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $desktop | Out-Null
$destination = Join-Path $installDirectory 'OPIc_Recorder.exe'
Copy-Item -LiteralPath $ExecutablePath -Destination $destination -Force
$shell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path $desktop 'OPIc Voice Recorder.lnk'
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $destination
$shortcut.WorkingDirectory = $installDirectory
$iconSource = Join-Path $PSScriptRoot 'assets\opic-recorder.ico'
if (Test-Path -LiteralPath $iconSource) {
    # A content-specific path prevents Explorer from reusing an older cached icon.
    $iconHash = (Get-FileHash -LiteralPath $iconSource -Algorithm SHA256).Hash.Substring(0, 12)
    $iconTarget = Join-Path $installDirectory "opic-microphone-$iconHash.ico"
    Copy-Item -LiteralPath $iconSource -Destination $iconTarget -Force
    $shortcut.IconLocation = "$iconTarget,0"
} else {
    $shortcut.IconLocation = "$destination,0"
}
$shortcut.Description = 'OPIc Voice Recorder - microphone recorder'
$shortcut.Save()
Write-Host "Installed: $destination"
Write-Host "Shortcut: $shortcutPath"
