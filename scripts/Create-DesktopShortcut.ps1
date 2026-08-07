param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$loginPage = Join-Path $ProjectRoot "fronts\index.html"
$iconPath = Join-Path $ProjectRoot "assets\mental-health-assistant.ico"

if (-not (Test-Path -LiteralPath $loginPage -PathType Leaf)) {
    throw "Login page not found: $loginPage"
}
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Shortcut icon not found: $iconPath"
}

$desktopPath = [Environment]::GetFolderPath("Desktop")
if (-not $desktopPath) {
    throw "Unable to resolve the current user's Desktop path."
}

$shortcutBaseName = -join [char[]](0x5FC3, 0x7406, 0x5065, 0x5EB7, 0x667A, 0x80FD, 0x533B, 0x7597, 0x52A9, 0x624B)
$shortcutPath = Join-Path $desktopPath ($shortcutBaseName + ".lnk")
$windowsDirectory = Split-Path -Parent ([Environment]::SystemDirectory)
$explorerPath = Join-Path $windowsDirectory "explorer.exe"
if (-not (Test-Path -LiteralPath $explorerPath -PathType Leaf)) {
    throw "Windows Explorer not found: $explorerPath"
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $explorerPath
$shortcut.Arguments = '"' + $loginPage + '"'
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = $iconPath + ",0"
$shortcut.Description = "Launch Mental Health Intelligent Medical Assistant"
$shortcut.WindowStyle = 1
$shortcut.Save()

$verified = $shell.CreateShortcut($shortcutPath)
[PSCustomObject]@{
    ShortcutPath = $shortcutPath
    TargetPath = $verified.TargetPath
    Arguments = $verified.Arguments
    WorkingDirectory = $verified.WorkingDirectory
    IconLocation = $verified.IconLocation
}
