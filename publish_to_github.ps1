$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
& .\.venv\Scripts\python.exe .\meta_india.py sync --max-new 1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git add data/state.json docs/status.json docs/downloads/meta_india_reports_latest.xlsx
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) { Write-Host "No new data to publish."; exit 0 }
git commit -m "Update Meta India report data"
git pull --rebase origin main
git push origin main
