Write-Host "--- Pytest (live) ---" -ForegroundColor Cyan
python -m pytest tests/qualification/ -m "live" -v
if ($LASTEXITCODE -eq 0) { Write-Host "PASSED" -ForegroundColor Green }
else { Write-Host "FAILED" -ForegroundColor Red }
exit $LASTEXITCODE
