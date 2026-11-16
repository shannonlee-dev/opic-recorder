param(
    [string]$FolderPath = (Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'Speaking_Recordings')
)
$ErrorActionPreference = 'Stop'
$iconSource = Join-Path $PSScriptRoot 'assets\speaking-recordings.ico'
if (-not (Test-Path -LiteralPath $iconSource -PathType Leaf)) {
    throw "Icon not found: $iconSource"
}
if (-not (Test-Path -LiteralPath $FolderPath -PathType Container)) {
    throw "Recording folder not found: $FolderPath"
}
$folder = Get-Item -LiteralPath $FolderPath
$hash = (Get-FileHash -LiteralPath $iconSource -Algorithm SHA256).Hash.Substring(0, 12)
$iconName = ".speaking-recordings-$hash.ico"
$iconTarget = Join-Path $folder.FullName $iconName
if (-not (Test-Path -LiteralPath $iconTarget)) {
    Copy-Item -LiteralPath $iconSource -Destination $iconTarget
}
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class SpeakingFolderIcon {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool WritePrivateProfileString(string section, string key, string value, string path);
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    public static extern void SHChangeNotify(uint change, uint flags, string item1, IntPtr item2);
}
'@
$ini = Join-Path $folder.FullName 'desktop.ini'
if (-not (Test-Path -LiteralPath $ini)) {
    [IO.File]::WriteAllText($ini, "[.ShellClassInfo]`r`n", [Text.Encoding]::Unicode)
}
# Preserve other desktop.ini settings and all recording files.
if (-not [SpeakingFolderIcon]::WritePrivateProfileString('.ShellClassInfo', 'IconResource', "$iconName,0", $ini)) {
    throw "Could not update folder icon: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}
foreach ($path in @($ini, $iconTarget)) {
    $item = Get-Item -LiteralPath $path -Force
    $item.Attributes = $item.Attributes -bor [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System
}
$folder.Attributes = $folder.Attributes -bor [IO.FileAttributes]::ReadOnly
# Notify Explorer about this folder, without restarting the desktop shell.
[SpeakingFolderIcon]::SHChangeNotify(0x00002000, 0x0005, $folder.FullName, [IntPtr]::Zero)
Write-Host "Folder icon installed: $($folder.FullName)"
