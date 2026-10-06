from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output" / "meta_india_reports_latest.xlsx"
app = FastAPI(title="Meta India Report Extractor")

def page(message: str = "") -> str:
    exists = OUT.exists()
    link = '<p><a href="/download">Download latest Excel</a></p>' if exists else "<p>No Excel generated yet.</p>"
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Meta India Report Extractor</title>
<style>body{{font-family:Segoe UI,Arial;max-width:900px;margin:40px auto;padding:0 20px}}input{{width:100%;padding:10px}}button{{padding:10px 16px;margin-top:10px}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px}}</style></head><body>
<h1>Meta India Report Extractor</h1>
<p><b>Browser-safe mode:</b> Sync opens the Meta hub once in Chrome instead of Python requests, then fetches at most one new PDF. No URL guessing, no HEAD probes, no retries.</p>
<h2>Automatic discovery</h2><form method="post" action="/sync"><button>Open Meta once in Chrome + sync one PDF</button></form>
<h2>Known direct PDF URL</h2><form method="post" action="/direct"><input name="pdf_url" placeholder="Paste the official direct .pdf URL"><button>Download + parse this PDF</button></form>
{link}<pre>{message}</pre></body></html>'''

@app.get("/", response_class=HTMLResponse)
def home(): return page()

@app.post("/sync", response_class=HTMLResponse)
def sync():
    r = subprocess.run([sys.executable, str(ROOT/"meta_india.py"), "sync", "--max-new", "1"], cwd=ROOT, text=True, capture_output=True)
    return page((r.stdout + "\n" + r.stderr)[-12000:])

@app.post("/direct", response_class=HTMLResponse)
def direct(pdf_url: str = Form(...)):
    r = subprocess.run([sys.executable, str(ROOT/"meta_india.py"), "direct", "--pdf-url", pdf_url], cwd=ROOT, text=True, capture_output=True)
    return page((r.stdout + "\n" + r.stderr)[-12000:])

@app.get("/download")
def download():
    if not OUT.exists():
        return RedirectResponse("/")
    return FileResponse(OUT, filename="meta_india_reports_latest.xlsx")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=False)
