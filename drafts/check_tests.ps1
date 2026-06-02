Write-Host "--- Pytest (offline) ---" -ForegroundColor Cyan
python -m pytest tests/unit/ tests/integration/ tests/qualification/ -m "not live"
if ($LASTEXITCODE -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }
exit $LASTEXITCODE
