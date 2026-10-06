# Meta India low-request report pipeline

This project was designed to avoid the HTTP-429 problem caused by probing hundreds of candidate Meta URLs.

## Request behavior

`python meta_india.py sync --max-new 1` has a **hard budget of 2 Meta HTTP requests**:

1. exactly one GET to the Regulatory Transparency Reports hub;
2. at most one GET for one newly discovered PDF.

There are **no HEAD requests, no guessed URLs, no automatic retries, and redirects are disabled**. If Meta returns 429, the program stops immediately.

If you already know the official direct PDF URL:

```powershell
python meta_india.py direct --pdf-url "https://...file.pdf"
```

that mode makes **exactly one Meta HTTP request total**: the PDF GET.

A literal one-request workflow cannot both discover an unknown file and download its bytes unless Meta puts the PDF bytes in the listing response. So `direct` is the exact-one-request mode; `sync` is the minimum practical automatic mode.

## Accuracy model

The PDF is parsed deterministically with `pdfplumber`, not by an LLM. The pipeline validates dates, row counts, duplicates, rates, suspicious truncated values, and known policy labels. In strict mode (default), a suspicious/unsupported report is **not silently added** to the master dataset; an audit JSON is written to `review/` instead.

The Excel export uses `template.xlsx`, which is the workbook supplied for this project, preserving its four-sheet layout:

- Data Notes
- Monthly Summary
- Trend Charts
- Master Data

## Windows quick start

1. Extract the ZIP.
2. Double-click `setup.bat` once.
3. Double-click `run_sync.bat` to try automatic discovery with at most 2 Meta requests.
4. Or double-click `run_web.bat` and open `http://127.0.0.1:8000`.

Generated workbook:

`output/meta_india_reports_latest.xlsx`

A copy for GitHub Pages is written to:

`docs/downloads/meta_india_reports_latest.xlsx`

## Direct PDF mode

If the hub response does not expose direct PDFs, open the report in your browser, copy the official **direct .pdf URL**, then run:

```powershell
.\.venv\Scripts\python.exe .\meta_india.py direct --pdf-url "PASTE_DIRECT_PDF_URL"
```

This is exactly one Meta request and is the safest mode for avoiding rate limits.

## Historical backfill

For maximum accuracy and minimal load, process already-downloaded historical PDFs with **zero Meta requests**:

```powershell
.\.venv\Scripts\python.exe .\meta_india.py file --pdf-file "C:\path\to\India-report.pdf"
```

Repeat for each historical PDF. The script merges validated rows into `data/state.json` and regenerates the same Excel file each time.

## Free public website

GitHub Pages can host `docs/` for free, but Pages cannot run Python. Because Meta has rate-limited cloud runners, the reliable free architecture is:

- extraction runs on your Windows PC;
- `publish_to_github.ps1` pushes only `state.json`, `status.json`, and the generated XLSX;
- GitHub Pages serves the static site and spreadsheet.

You can schedule `publish_to_github.ps1` weekly using Windows Task Scheduler.
