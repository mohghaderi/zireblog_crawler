# Crawler Tooling

This folder contains a small Python crawler (`crawl.py`) that reads configuration from the repo-level `.env` file, discovers pages under a given prefix, and saves matching HTML pages under `out/`.

## Requirements
- Python 3.9+
- `pip`

## Create a virtual environment
From the repo root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Then install dependencies:

```bash
./.venv/Scripts/python3 -m pip install --upgrade -r crawler/requirements.txt
```

## Configure `.env`
Create or update the repo-level `.env` file (same folder as `package.json`) with:

```
CRAWL_URL_PREFIX="https://example.com"
CRAWL_MATCH_REGEX="/post-\\d+/"
CRAWL_MAX_PAGES="0"
CRAWL_TIMEOUT="10"
CRAWL_LOG_LEVEL="INFO"
```

Notes:
- `CRAWL_URL_PREFIX` and `CRAWL_MATCH_REGEX` are required.
- `CRAWL_MAX_PAGES=0` means unbounded.
- `CRAWL_TIMEOUT` is per-request timeout (seconds).
- `CRAWL_LOG_LEVEL` controls logging verbosity.

You can copy the sample values from `.env-example` at the repo root.

## Run the crawler
From the repo root, with the virtual environment activated:

```bash
python crawler/crawl.py
```

Or use the helper script (auto-loads `.env` and installs requirements):

```bash
crawler/run_crawler.sh
```

The crawler writes matched HTML files into `out/<hostname>/` and records metadata in `out/matches.jsonl`.
