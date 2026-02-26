#!/usr/bin/env python3
"""Download Picofile assets referenced in JSON files under out/."""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DEFAULT_OUT_ROOT = REPO_ROOT / "out"
URL_PATTERN = re.compile(r"https?://(?:[A-Za-z0-9-]+\.)*picofile\.com/[^\s\"'<>\\)]+", re.IGNORECASE)
ESCAPED_URL_PATTERN = re.compile(
    r"https?:\\/\\/(?:[A-Za-z0-9-]+\.)*picofile\.com\\/[^\s\"'<>\\)]+",
    re.IGNORECASE,
)
DEFAULT_TIMEOUT = 20


def _iter_json_files(out_root: Path) -> list[Path]:
    return sorted(path for path in out_root.rglob("*.json") if path.is_file())


def _extract_picofile_urls(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    urls = {match.group(0) for match in URL_PATTERN.finditer(text)}
    urls.update(match.group(0).replace("\\/", "/") for match in ESCAPED_URL_PATTERN.finditer(text))
    return urls


def _target_path_for(url: str, target_dir: Path) -> Path:
    parsed = urlparse(url)
    basename = Path(parsed.path).name or "picofile_asset"
    if "." not in basename:
        basename = f"{basename}.bin"
    return target_dir / basename


def _download_file(url: str, dest: Path, timeout: int) -> bool:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; picofile-downloader/1.0)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logging.warning("Failed to download %s: %s", url, exc)
        return False

    dest.write_bytes(data)
    return True


def download_picofile(out_root: Path, timeout: int) -> tuple[int, int, int]:
    json_files = _iter_json_files(out_root)
    all_urls: set[str] = set()
    for json_file in json_files:
        found = _extract_picofile_urls(json_file)
        if found:
            logging.info("Found %d Picofile URL(s) in %s", len(found), json_file.relative_to(REPO_ROOT))
        all_urls.update(found)

    picofile_urls = sorted(all_urls)
    target_dir = out_root / "picofile"
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped = 0
    failed = 0

    for index, picofile_url in enumerate(picofile_urls, start=1):
        output_path = _target_path_for(picofile_url, target_dir)
        logging.info(
            "Processing [%d/%d] %s",
            index,
            len(picofile_urls),
            output_path.relative_to(REPO_ROOT),
        )
        if output_path.exists():
            skipped += 1
            logging.info("Ignored existing file: %s", output_path.relative_to(REPO_ROOT))
            continue

        if _download_file(picofile_url, output_path, timeout):
            downloaded += 1
            logging.info("Downloaded %s -> %s", picofile_url, output_path.relative_to(REPO_ROOT))
        else:
            failed += 1

    return downloaded, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find Picofile URLs in out/**/*.json and download them into out/picofile."
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help=f"Root directory containing JSON files (default: {DEFAULT_OUT_ROOT})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_root = args.out_root.resolve()
    if not out_root.exists():
        raise SystemExit(f"Directory does not exist: {out_root}")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be greater than 0")

    downloaded, skipped, failed = download_picofile(out_root, args.timeout)
    logging.info(
        "Picofile download finished. downloaded=%d skipped=%d failed=%d",
        downloaded,
        skipped,
        failed,
    )


if __name__ == "__main__":
    main()
