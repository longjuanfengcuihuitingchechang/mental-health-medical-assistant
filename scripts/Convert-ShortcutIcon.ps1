param(
    [string]$SourcePath,
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $SourcePath) {
    $SourcePath = Join-Path $projectRoot "3f20e328-8f06-4c31-882c-de2c882eaeea.jpg"
}
if (-not $OutputPath) {
    $OutputPath = Join-Path $projectRoot "assets\mental-health-assistant.ico"
}

if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw "Source image not found: $SourcePath"
}

Add-Type -AssemblyName System.Drawing

$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$source = [System.Drawing.Image]::FromFile($SourcePath)
$bitmap = New-Object System.Drawing.Bitmap 256, 256, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$pngStream = New-Object System.IO.MemoryStream
$fileStream = $null
$writer = $null

try {
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.DrawImage($source, 0, 0, 256, 256)
    $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)

    $pngBytes = $pngStream.ToArray()
    $fileStream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::Create)
    $writer = New-Object System.IO.BinaryWriter $fileStream

    $writer.Write([UInt16]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]1)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([Byte]0)
    $writer.Write([UInt16]1)
    $writer.Write([UInt16]32)
    $writer.Write([UInt32]$pngBytes.Length)
    $writer.Write([UInt32]22)
    $writer.Write($pngBytes)
}
finally {
    if ($writer) { $writer.Dispose() }
    elseif ($fileStream) { $fileStream.Dispose() }
    $pngStream.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
    $source.Dispose()
}

Get-Item -LiteralPath $OutputPath | Select-Object FullName, Length, LastWriteTime
