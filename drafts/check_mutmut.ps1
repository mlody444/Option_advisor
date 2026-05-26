# Run mutation testing via WSL. Must be run from the project root.

Write-Host "--- Mutmut (mutation testing) ---" -ForegroundColor Cyan

$wslPath = wsl wslpath -u ($PWD.Path -replace '\\', '/')
if (-not $wslPath) {
    Write-Host "FAILED - WSL not available or not configured" -ForegroundColor Red
    exit 1
}

$script = (Get-Content "drafts\check_mutmut.sh" -Raw) -replace "`r`n", "`n"
$script | wsl bash --login
$run_exit = $LASTEXITCODE

if ($run_exit -eq 0) { Write-Host "PASSED - no surviving mutations" -ForegroundColor Green }
else { Write-Host "FAILED - surviving mutations detected" -ForegroundColor Red }

exit $run_exit
