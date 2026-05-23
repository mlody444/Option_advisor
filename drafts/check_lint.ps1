Write-Host "--- Ruff lint ---" -ForegroundColor Cyan
ruff check drafts/test_connection.py
if ($LASTEXITCODE -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }
exit $LASTEXITCODE
