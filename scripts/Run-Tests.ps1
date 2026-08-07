param([string]$PythonCommand)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not $PythonCommand) {
    $PythonCommand = if (Test-Path -LiteralPath $venvPython) {
        $venvPython
    }
    else {
        "python"
    }
}

Push-Location -LiteralPath $backendRoot
try {
    & $PythonCommand -m compileall -q app scripts
    if ($LASTEXITCODE -ne 0) { throw "Python compile check failed" }
    & $PythonCommand -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "Test suite failed" }
}
finally {
    Pop-Location
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    throw "Node.js is required for frontend JavaScript syntax checks"
}
Get-ChildItem -LiteralPath (Join-Path $projectRoot "fronts") -Recurse -Filter "*.js" | ForEach-Object {
    & $nodeCommand.Source --check $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "JavaScript syntax check failed: $($_.FullName)" }
}

$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $gitCommand) {
    throw "Git is required for sensitive-file boundary checks"
}
& (Join-Path $PSScriptRoot "Test-SensitiveFiles.ps1")
if ($LASTEXITCODE -ne 0) { throw "Sensitive-file checks failed" }
& $gitCommand.Source -C $projectRoot diff --check
if ($LASTEXITCODE -ne 0) { throw "Git whitespace check failed" }

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if ($null -ne $dockerCommand) {
    $previousDatabaseHostDir = $env:DATABASE_HOST_DIR
    $previousPepperHostFile = $env:AUTH_PEPPER_HOST_FILE
    try {
        $env:DATABASE_HOST_DIR = Join-Path $projectRoot "runtime"
        $env:AUTH_PEPPER_HOST_FILE = Join-Path $projectRoot "private\auth_pepper.key"
        & $dockerCommand.Source compose --env-file (Join-Path $projectRoot ".env.example") -f (Join-Path $projectRoot "docker-compose.yml") config --quiet
        if ($LASTEXITCODE -ne 0) { throw "Docker Compose configuration validation failed" }
    }
    finally {
        $env:DATABASE_HOST_DIR = $previousDatabaseHostDir
        $env:AUTH_PEPPER_HOST_FILE = $previousPepperHostFile
    }
}
else {
    Write-Warning "Docker not found; Compose validation skipped"
}
