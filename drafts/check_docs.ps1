Write-Host "--- Pydoclint (docstrings) ---" -ForegroundColor Cyan
pydoclint drafts/test_connection.py
if ($LASTEXITCODE -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }
exit $LASTEXITCODE
