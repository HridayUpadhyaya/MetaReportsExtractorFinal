# Browser-safe Meta sync fix

This build removes the code path that produced the previous `400 Client Error` from `requests.get()` on the Meta hub.

## What changed
- `sync` no longer uses Python `requests` for the Meta reports hub.
- It opens the hub once in real Google Chrome (or Playwright Chromium fallback).
- It blocks only images/media/fonts to reduce noise; scripts/XHR remain enabled because Meta needs them to render.
- It does not guess report URLs, send HEAD probes, retry failures, or run concurrent Meta requests.
- It fetches at most ONE new PDF per run.
- `direct` mode also uses the browser context instead of Python requests.
- `file` mode remains available and makes zero Meta requests.

## Install/update
Double-click `setup.bat` once after replacing the files.

## Run
Double-click `run_sync.bat`.

A Chrome window should open. Leave it open until the terminal finishes.

Or PowerShell:

```powershell
.\.venv\Scripts\python.exe .\meta_india.py sync --max-new 1
```

## Direct known PDF URL

```powershell
.\.venv\Scripts\python.exe .\meta_india.py direct --pdf-url "https://...actual-report.pdf"
```

## Local PDF (zero scripted Meta requests)

```powershell
.\.venv\Scripts\python.exe .\meta_india.py file --pdf-file "C:\path\India-Monthly-Report.pdf"
```

## Important
No software can guarantee Meta will never reject automation. This fix specifically removes the old Python `requests.get(hub)` code that was producing your HTTP 400. If Meta rejects even Chrome automation, use `file` mode; parsing/export remains fully automatic and only the PDF download is manual.
