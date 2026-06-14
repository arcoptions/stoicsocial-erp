$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$pythonPath = Join-Path $repoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $pythonPath)) {
    Write-Error "Python venv not found at $pythonPath"
    exit 1
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)] [string] $Name,
        [Parameter(Mandatory = $true)] [string[]] $Arguments
    )

    Write-Host ""
    Write-Host "==== $Name ====" -ForegroundColor Cyan
    & $pythonPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Step failed: $Name" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Invoke-Step -Name "Django checks" -Arguments @("manage.py", "check")
Invoke-Step -Name "DB migrations" -Arguments @("manage.py", "migrate")
Invoke-Step -Name "Seed QA scenarios" -Arguments @("manage.py", "seed_qa_scenarios")
Invoke-Step -Name "Seed finance sample data" -Arguments @("manage.py", "seed_finance_sample_data")
Invoke-Step -Name "Run tests" -Arguments @("manage.py", "test")
Invoke-Step -Name "Smoke probes" -Arguments @("scripts/qa_smoke.py")

Write-Host ""
Write-Host "QA daily run completed successfully." -ForegroundColor Green
