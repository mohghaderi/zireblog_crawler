#!/usr/bin/env python3
"""Simple domain-aware BFS crawler that stores matched HTML pages."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urldefrag, urlparse

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from requests.exceptions import RequestException

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
OUTPUT_DIR = REPO_ROOT / "out"
METADATA_FILE = OUTPUT_DIR / "matches.jsonl"
DEFAULT_MAX_PAGES = 0
DEFAULT_TIMEOUT = 100
MAX_FILENAME_BYTES = 240


def _env(name: str, required: bool = True) -> str:
    value = os.environ.get(name)
    if required and not value:
        raise RuntimeError(f"{name} must be set")
    return value or ""


def _normalize_prefix(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("CRAWL_URL_PREFIX must start with http:// or https://")
    clean = parsed._replace(fragment="", params="", query="").geturl().rstrip("/")
    return clean


def _normalize_url(raw: str) -> str | None:
    cleaned, _ = urldefrag(raw)
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    normalized = parsed._replace(path=path, params="", fragment="").geturl()
    return normalized


def _hostname_from_url(raw: str) -> str:
    parsed = urlparse(raw)
    hostname = parsed.hostname
    if not hostname:
        raise RuntimeError("CRAWL_URL_PREFIX must include a hostname")
    return hostname.lower()


def _is_same_hostname(url: str, hostname: str) -> bool:
    parsed = urlparse(url)
    candidate_hostname = parsed.hostname
    return bool(candidate_hostname and candidate_hostname.lower() == hostname)


def _sanitize_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    return sanitized.strip("_") or "segment"


def _truncate_for_filename(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    # Preserve valid UTF-8 boundaries when truncating by byte length.
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _pick_unique_path(target_dir: Path, stem: str, suffix: str = ".html") -> Path:
    candidate = target_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        next_candidate = target_dir / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def _extract_post_number_from_matches(matches: Iterable[str]) -> str | None:
    for match in matches:
        number_match = re.search(r"\d+", match)
        if number_match:
            return number_match.group(0)
    return None


def _save_html(url: str, text: str, post_number: str | None) -> Path:
    hashed = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    parsed = urlparse(url)
    netloc = _sanitize_component(parsed.netloc or "site")
    path_segments = [seg for seg in (parsed.path or "").split("/") if seg]
    name_segment = path_segments[-1] if path_segments else "root"
    safe_segment = _sanitize_component(name_segment)
    reserved_bytes = len(f"_{hashed}.html".encode("utf-8"))
    safe_segment = _truncate_for_filename(safe_segment, MAX_FILENAME_BYTES - reserved_bytes) or "segment"
    if post_number:
        filename_stem = f"post_{post_number}"
    else:
        filename_stem = f"{safe_segment}_{hashed}"
    target_dir = OUTPUT_DIR / netloc

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = _pick_unique_path(target_dir, filename_stem)
    target_file.write_text(text, encoding="utf-8")
    logging.info("Wrote HTML page for %s to %s", url, target_file.relative_to(REPO_ROOT))
    return target_file


def _record_match(url: str, path: Path, matches: Iterable[str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    metadata = {
        "url": url,
        "file": str(path.relative_to(REPO_ROOT)),
        "matches": list(matches),
    }
    with METADATA_FILE.open("a", encoding="utf-8") as handle:
        json.dump(metadata, handle)
        handle.write("\n")
    logging.info("Recorded metadata for %s (matches=%d) in %s", url, len(matches), METADATA_FILE.relative_to(REPO_ROOT))


def _extract_links(html: str, base_url: str) -> Iterable[str]:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a[href]"):
        href = anchor["href"].strip()
        if not href:
            continue
        joined = urljoin(base_url, href)
        normalized = _normalize_url(joined)
        if normalized:
            yield normalized
        else:
            logging.debug("Ignored href %s on %s (unsupported or non-HTTP scheme)", href, base_url)


def crawl(prefix: str, matcher: re.Pattern[str], max_pages: int, timeout: int) -> tuple[int, int]:
    session = requests.Session()
    queue = deque([prefix])
    discovered: set[str] = {prefix}
    visited: set[str] = set()
    saved = 0
    processed = 0
    allowed_hostname = _hostname_from_url(prefix)
    log_discovered = os.environ.get("CRAWL_LOG_DISCOVERED") == "1"
    logging.info(
        "Crawler config: prefix=%s hostname=%s regex=%s max_pages=%s timeout=%d",
        prefix,
        allowed_hostname,
        matcher.pattern,
        "unbounded" if max_pages == 0 else max_pages,
        timeout,
    )

    while queue and (max_pages == 0 or processed < max_pages):
        current = queue.popleft()
        if current in visited:
            continue
        logging.info("Fetching %s", current)
        try:
            response = session.get(current, timeout=timeout, headers={"User-Agent": "crawler"})
            response.raise_for_status()
        except RequestException as exc:
            logging.warning("Skipping %s: %s", current, exc)
            visited.add(current)
            continue

        processed += 1
        # Match only against the URL; do not scan the full page content.
        matches = [match.group(0) for match in matcher.finditer(current)]
        if matches:
            post_number = _extract_post_number_from_matches(matches)
            path = _save_html(current, response.text, post_number)
            _record_match(current, path, matches)
            saved += 1
            logging.info("Saved %s (%d matches)", path.relative_to(REPO_ROOT), len(matches))

        for candidate in _extract_links(response.text, current):
            if log_discovered:
                logging.debug("Discovered %s on %s", candidate, current)
            if _is_same_hostname(candidate, allowed_hostname):
                if candidate in discovered:
                    continue
                discovered.add(candidate)
                queue.append(candidate)
#             else:
#                 logging.info(
#                     "Ignored %s (found on %s): outside allowed hostname %s",
#                     candidate,
#                     current,
#                     allowed_hostname,
#                 )
        visited.add(current)

    if max_pages and processed >= max_pages:
        logging.info("Stopped because CRAWL_MAX_PAGES=%d was reached", max_pages)
    logging.info("Crawled %d pages, saved %d matches", processed, saved)
    return processed, saved


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("CRAWL_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    env_file = REPO_ROOT / ".env"
    load_dotenv(env_file, override=False)

    raw_prefix = _env("CRAWL_URL_PREFIX")
    raw_regex = _env("CRAWL_MATCH_REGEX")
    prefix = _normalize_prefix(raw_prefix)
    matcher = re.compile(raw_regex, flags=re.MULTILINE)
    max_pages_value = os.environ.get("CRAWL_MAX_PAGES")
    try:
        max_pages = int(max_pages_value) if max_pages_value is not None else DEFAULT_MAX_PAGES
        if max_pages < 0:
            raise ValueError
    except (TypeError, ValueError):
        max_pages = DEFAULT_MAX_PAGES
    timeout_value = os.environ.get("CRAWL_TIMEOUT")
    try:
        timeout = int(timeout_value) if timeout_value else DEFAULT_TIMEOUT
        if timeout <= 0:
            raise ValueError
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    crawl(prefix, matcher, max_pages, timeout)


if __name__ == "__main__":
    main()
