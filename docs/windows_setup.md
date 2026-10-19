# Windows setup and run guide (PowerShell)

Tested on Windows 10 with Python 3.14.7 and Microsoft Edge 155. Python 3.11 or newer is required.

## 1. Get the project

```powershell
git clone https://github.com/harjotsandhu24/supplierpulse-procurement-analytics.git
cd supplierpulse-procurement-analytics
```

## 2. Create the environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements-dev.txt   # exact versions used: requirements-lock.txt
pip install -e .
```

## 3. Run the pipeline

```powershell
python -m supplierpulse.pipeline            # about 30 seconds
python -m supplierpulse.pipeline --render   # also renders docs/screenshots/*.png and the PDF brief
```

The pipeline reads the committed snapshot `data/public/austin_po_lines_snapshot.parquet` and writes:

| Output | Location |
|---|---|
| Dashboard | `deliverables/SupplierPulse_Dashboard.html` |
| Excel workbook | `deliverables/SupplierPulse_Procurement_Analysis.xlsx` |
| Decision brief | `deliverables/SupplierPulse_Decision_Brief.pdf` (with `--render`) |
| Tables and metrics | `outputs/tables/*.csv`, `outputs/metrics.json` |
| SQL database / results | `data/processed/supplierpulse.duckdb`, `outputs/sql_results/*.csv` |
| Data-quality audit | `docs/data_quality_audit.md` |

Rendering uses the installed Microsoft Edge through Playwright. If Edge is missing, run `python -m playwright install chromium` once.

## 4. Run the tests

```powershell
pytest -m "not slow"   # ~4 min (includes the offline dashboard render test)
pytest                 # adds the full Excel recalculation (~8 min total)
```

## 5. Open the results

```powershell
start deliverables\SupplierPulse_Dashboard.html
start deliverables\SupplierPulse_Procurement_Analysis.xlsx
start deliverables\SupplierPulse_Decision_Brief.pdf
```

## 6. Optional: refresh from the live portal

The City rebuilds the dataset weekly, so a refresh changes the numbers.

```powershell
python -m supplierpulse.ingest --download --snapshot   # ~100 MB into data/raw/ (git-ignored), then rebuilds the snapshot
python -m supplierpulse.pipeline --render
```

If the download is blocked, download the CSV manually from https://data.austintexas.gov/d/3ebq-e9iz (Export → CSV) and save it as `data/raw/austin_po_lines_raw.csv`, then run `python -m supplierpulse.ingest --snapshot`.
