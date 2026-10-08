# Meta India low-request report pipeline

This project was designed to avoid the HTTP-429 problem caused by probing hundreds of candidate Meta URLs.

## Request behavior

`python meta_india.py sync --max-new 15` opens the Meta report hub once in a browser, then processes up to 15 missing editions:

1. one browser navigation to the Regulatory Transparency Reports hub;
2. at most 15 explicit PDF fetches, with already-cached PDFs reused.

There are **no HEAD probes, no guessed URLs, and no automatic retries**. Browser subresources and CDN redirects can create additional HTTP requests. If Meta returns 429, the program stops immediately.

If you already know the official direct PDF URL:

```powershell
python meta_india.py direct --pdf-url "https://...file.pdf"
```

that mode makes one explicit PDF fetch without opening the hub. CDN redirects are allowed.

Use `direct` for a known PDF URL and `sync` for automatic discovery and historical backfill.

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
3. Double-click `run_sync.bat` to discover and process up to 15 missing reports.
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

This fetches the known PDF without a hub navigation.

## Historical backfill

For maximum accuracy and minimal load, process already-downloaded historical PDFs with **zero Meta requests**:

```powershell
.\.venv\Scripts\python.exe .\meta_india.py file --pdf-file "C:\path\to\India-report.pdf"
```

Repeat for each historical PDF. The script merges validated rows into `data/state.json` and regenerates the same Excel file each time.

## Public spreadsheet explorer

Live site: https://hridayupadhyaya.github.io/MetaReportsExtractorFinal/

Select inclusive **reporting months** and Facebook, Instagram, and/or Threads. The preview shows matching periods, policy rows, totals, and missing coverage. Download a custom `.xlsx` containing the same four tabs, styles, dates, and native Excel charts as the complete workbook. The range uses the month in which a reporting period ends; PDF publication dates remain in Master Data. Early irregular periods retain their exact dates.

Custom exports run entirely in the visitor's browser, copying original validated cells from the published workbook. The pinned, MIT-licensed fflate 0.8.3 library is served locally; no CDN or external spreadsheet service is required. `docs/data.json` contains only public report fields and workbook row indexes. Dataset/workbook mismatches stop the export and ask the visitor to reload.

`run_web.bat` serves the same site locally at `http://127.0.0.1:8000/`. The local manual extraction controls are available at `/extractor`.

## Automatic updates and deployment

`Meta Reports Auto Sync` runs on GitHub Actions daily at **02:30 UTC (08:00 IST)**, or manually through Actions. GitHub may delay scheduled jobs. It discovers the official Meta hub once and processes up to **15** missing PDFs per run, keeping strict validation enabled. Successful rows update the workbook, preview dataset, status, and validation audit. Unsupported reports remain excluded; rate limiting or source format changes can delay ingestion.

`Deploy Report Explorer` publishes `docs/` through the GitHub Pages Actions deployment API after every sync completion and on website changes pushed to `main`. Its `workflow_run` trigger handles automated commits made with `GITHUB_TOKEN`, which do not trigger another push workflow. A failed sync still republishes the last committed validated dataset and audits. Your PC does not need to stay on.

The repository's Pages source must be **GitHub Actions**. The deploy workflow checks out the latest `main`, tests the public dataset, uploads a Pages artifact, and deploys it to the `github-pages` environment. Only the official PDF extractor needs Python; the public site is static.

Checks before publishing:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_site.mjs
```
