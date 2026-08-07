param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $gitCommand) { throw "Git is required for sensitive-file checks" }

$trackedSensitive = & $gitCommand.Source -C $projectRoot ls-files -- ".env" "private/**" "*.db" "*.sqlite" "*.sqlite3" "*.log" "*.key" "*.pem" "*.p12" "*.pfx" "*.crt"
if ($LASTEXITCODE -ne 0) { throw "Git sensitive-file query failed" }
if ($trackedSensitive) {
    throw "Sensitive runtime files are tracked by Git: $($trackedSensitive -join ', ')"
}

$sourceRoots = @("backend", "fronts", "scripts", "infrastructure", "SPECS")
$sourceExtensions = @(".py", ".js", ".html", ".css", ".md", ".sql", ".json", ".toml", ".yml", ".yaml", ".ps1", ".Dockerfile")
$sourceFiles = foreach ($relativeRoot in $sourceRoots) {
    $root = Join-Path $projectRoot $relativeRoot
    if (Test-Path -LiteralPath $root) {
        Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object {
            $_.Name -like "*Dockerfile" -or $_.Extension -in $sourceExtensions
        }
    }
}

$apiKeyPattern = ("s" + "k-") + "[A-Za-z0-9_-]{20,}"
$privateKeyPattern = ("BEGIN " + "(RSA |EC |OPENSSH )?PRIVATE KEY")
$valueHits = $sourceFiles | Select-String -Pattern @($apiKeyPattern, $privateKeyPattern) -CaseSensitive:$false
if ($valueHits) {
    $paths = $valueHits | Select-Object -ExpandProperty Path -Unique
    throw "Potential secret values found in source files: $($paths -join ', ')"
}

$frontendFiles = Get-ChildItem -LiteralPath (Join-Path $projectRoot "fronts") -Recurse -File
$frontendMarkers = @("DEEPSEEK_API_KEY", "AUTH_PEPPER_FILE", "initial_password", "BEGIN " + "PRIVATE KEY")
$frontendHits = $frontendFiles | Select-String -SimpleMatch -Pattern $frontendMarkers
if ($frontendHits) {
    $paths = $frontendHits | Select-Object -ExpandProperty Path -Unique
    throw "Server-only secret markers found in frontend files: $($paths -join ', ')"
}

Write-Output "Sensitive-file checks passed"
