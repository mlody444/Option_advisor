# Run all checks and print a summary at the end.
# Must be run from the project root directory.

$scripts = [ordered]@{
    "Ruff lint"   = ".\drafts\check_lint.ps1"
    "Ruff format" = ".\drafts\check_format.ps1"
    "Mypy"        = ".\drafts\check_types.ps1"
    "Pydoclint"   = ".\drafts\check_docs.ps1"
    "Security"    = ".\drafts\check_security.ps1"
}

$results = [ordered]@{}

foreach ($name in $scripts.Keys) {
    Write-Host ""
    & $scripts[$name]
    $results[$name] = ($LASTEXITCODE -eq 0)
}

# summary
Write-Host ""
Write-Host "--- Summary ---" -ForegroundColor Cyan
$any_failed = $false
foreach ($name in $results.Keys) {
    if ($results[$name]) {
        Write-Host "  PASS  $name" -ForegroundColor Green
    } else {
        Write-Host "  FAIL  $name" -ForegroundColor Red
        $any_failed = $true
    }
}

Write-Host ""
if ($any_failed) {
    Write-Host "Some checks failed." -ForegroundColor Red
    exit 1
} else {
    Write-Host "All checks passed." -ForegroundColor Green
    exit 0
}
