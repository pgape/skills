# archery_pat.ps1 - PAT bridge wrapper for the archery-cli skill (Windows)
# Reads PAT from env: ARCHERY_PAT (or ARCHERY_CLI_PAT); --pat also works.
# Examples:
#   $env:ARCHERY_PAT = "arp_pat_xxx"
#   .\archery_pat.ps1 whoami
#   .\archery_pat.ps1 instances
#   .\archery_pat.ps1 query --instance "eerp-qa-new" --db eerp_sales --sql "select 1"
# Bypass execution policy:
#   powershell -ExecutionPolicy Bypass -File archery_pat.ps1 whoami

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript = Join-Path $ScriptDir "archery_pat.py"

# Python resolution order: env ARCHERY_CLI_PYTHON > python on PATH > known install path
$PyExe = $env:ARCHERY_CLI_PYTHON
if (-not $PyExe) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $PyExe = $cmd.Source }
}
if (-not $PyExe) { $PyExe = "D:/Program Files/Python/Python311/python.exe" }

if (-not (Test-Path $PyScript)) {
    Write-Error "archery_pat.py not found: $PyScript"
    exit 1
}
if (-not (Test-Path $PyExe)) {
    Write-Error "Python not found: $PyExe (set ARCHERY_CLI_PYTHON to override)"
    exit 1
}

& $PyExe $PyScript @args
exit $LASTEXITCODE
