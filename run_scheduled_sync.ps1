param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = 'C:\Program Files\Python313\python.exe'
$sitePackages = Join-Path $projectRoot '.venv\Lib\site-packages'
if (-not (Test-Path -LiteralPath $python)) { throw "Server Python not found: $python" }
if (-not (Test-Path -LiteralPath $sitePackages)) { throw "Project packages not found: $sitePackages" }
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$sitePackages;$env:PYTHONPATH" } else { $sitePackages }
Set-Location -LiteralPath $projectRoot
if ($ValidateOnly) {
    $probeLog = Join-Path $projectRoot 'logs\task_validation.log'
    $stdoutLog = Join-Path $projectRoot 'logs\task_validation.stdout.log'
    $stderrLog = Join-Path $projectRoot 'logs\task_validation.stderr.log'
    $result = Start-Process -FilePath $python -ArgumentList @('-m', 'src.main', 'validate-mapping') -WorkingDirectory $projectRoot -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru
    @("Exit code: $($result.ExitCode)", '--- stdout ---', (Get-Content -LiteralPath $stdoutLog -Raw -ErrorAction SilentlyContinue), '--- stderr ---', (Get-Content -LiteralPath $stderrLog -Raw -ErrorAction SilentlyContinue)) | Set-Content -LiteralPath $probeLog -Encoding UTF8
    exit $result.ExitCode
} else {
    $stdoutLog = Join-Path $projectRoot 'logs\scheduled_sync.stdout.log'
    $stderrLog = Join-Path $projectRoot 'logs\scheduled_sync.stderr.log'
    $result = Start-Process -FilePath $python -ArgumentList @('-m', 'src.main', 'sync') -WorkingDirectory $projectRoot -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -Wait -PassThru
    exit $result.ExitCode
}
