param(
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

Set-Location -LiteralPath $projectRoot

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonCommand -m venv $venvPath
}

& $venvPython -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'; print(sys.version)"
& (Join-Path $PSScriptRoot "Run-Tests.ps1") -PythonCommand $venvPython
