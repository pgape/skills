# archery.ps1 - Archery SQL 审核平台命令包装器（PAT 认证）
# 用法:
#   .\archery.ps1 whoami --pat arp_pat_xxx
#   .\archery.ps1 workflow-list --status workflow_manreviewing
#   .\archery.ps1 workflow-cancel --id 12345 --remark "误提交取消"
# 或在任意目录:
#   powershell -ExecutionPolicy Bypass -File archery.ps1 query --instance "eerp-qa-new" --db eerp_sales --sql "select 1"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyScript = Join-Path $ScriptDir "archery_api.py"
$PyExe = "D:/Program Files/Python/Python311/python.exe"

if (-not (Test-Path $PyScript)) {
    Write-Error "找不到 archery_api.py: $PyScript"
    exit 1
}

& $PyExe $PyScript @args
exit $LASTEXITCODE