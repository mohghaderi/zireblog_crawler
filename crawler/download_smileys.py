#!/usr/bin/env python3
"""Download Blogsky smiley assets referenced in JSON files under out/."""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DEFAULT_OUT_ROOT = REPO_ROOT / "out"
SMILEY_PREFIX = "http://www.blogsky.com/images/smileys/"
URL_PATTERN = re.compile(r"http://www\.blogsky\.com/images/smileys/[^\s\"'<>\\)]+")
ESCAPED_URL_PATTERN = re.compile(r"http:\\/\\/www\.blogsky\.com\\/images\\/smileys\\/[^\s\"'<>\\)]+")
DEFAULT_TIMEOUT = 20


def _iter_json_files(out_root: Path) -> list[Path]:
    return sorted(path for path in out_root.rglob("*.json") if path.is_file())


def _extract_smiley_urls(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    urls = {match.group(0) for match in URL_PATTERN.finditer(text)}
    urls.update(match.group(0).replace("\\/", "/") for match in ESCAPED_URL_PATTERN.finditer(text))
    return urls


def _target_path_for(smiley_url: str, target_dir: Path, seen_names: set[str]) -> Path:
    parsed = urlparse(smiley_url)
    basename = Path(parsed.path).name or "smiley"
    if "." not in basename:
        basename = f"{basename}.img"

    if basename not in seen_names:
        seen_names.add(basename)
        return target_dir / basename

    digest = hashlib.sha256(smiley_url.encode("utf-8")).hexdigest()[:8]
    stem = Path(basename).stem or "smiley"
    suffix = Path(basename).suffix or ".img"
    unique_name = f"{stem}_{digest}{suffix}"
    seen_names.add(unique_name)
    return target_dir / unique_name


def _download_file(url: str, dest: Path, timeout: int) -> bool:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; smiley-downloader/1.0)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        logging.warning("Failed to download %s: %s", url, exc)
        return False

    dest.write_bytes(data)
    return True


def download_smileys(out_root: Path, timeout: int) -> tuple[int, int, int]:
    json_files = _iter_json_files(out_root)
    all_urls: set[str] = set()
    for json_file in json_files:
        found = _extract_smiley_urls(json_file)
        if found:
            logging.info("Found %d smiley URL(s) in %s", len(found), json_file.relative_to(REPO_ROOT))
        all_urls.update(found)

    smiley_urls = sorted(url for url in all_urls if url.startswith(SMILEY_PREFIX))
    target_dir = out_root / "smileys"
    target_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    failed = 0
    skipped = 0
    seen_names: set[str] = set()

    for smiley_url in smiley_urls:
        output_path = _target_path_for(smiley_url, target_dir, seen_names)
        if output_path.exists():
            skipped += 1
            logging.info("Skipping existing %s", output_path.relative_to(REPO_ROOT))
            continue

        if _download_file(smiley_url, output_path, timeout):
            downloaded += 1
            logging.info("Downloaded %s -> %s", smiley_url, output_path.relative_to(REPO_ROOT))
        else:
            failed += 1

    return downloaded, skipped, failed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find Blogsky smiley URLs in out/**/*.json and download them into out/smileys."
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

    downloaded, skipped, failed = download_smileys(out_root, args.timeout)
    logging.info(
        "Smiley download finished. downloaded=%d skipped=%d failed=%d",
        downloaded,
        skipped,
        failed,
    )


if __name__ == "__main__":
    main()
