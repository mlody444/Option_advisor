Write-Host "--- Bandit (code security) ---" -ForegroundColor Cyan
bandit -r drafts/test_connection.py
$bandit_exit = $LASTEXITCODE
if ($bandit_exit -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }

Write-Host ""
Write-Host "--- Pip-audit (dependency CVEs) ---" -ForegroundColor Cyan
pip-audit
$audit_exit = $LASTEXITCODE
if ($audit_exit -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }

if ($bandit_exit -ne 0 -or $audit_exit -ne 0) { exit 1 }
exit 0
