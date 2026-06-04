Write-Host "--- Coverage (branch) ---" -ForegroundColor Cyan
python -m pytest tests/ -m "not live" --cov drafts --cov-branch --cov-fail-under=100 --cov-report=term-missing -q
if ($LASTEXITCODE -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }
exit $LASTEXITCODE
