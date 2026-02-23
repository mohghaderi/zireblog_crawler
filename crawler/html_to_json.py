#!/usr/bin/env python3
"""Convert crawled Blogsky HTML files to structured JSON."""
from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
DEFAULT_OUT_ROOT = REPO_ROOT / "out"

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    normalized = value.translate(_DIGIT_MAP)
    digits = re.sub(r"[^\d]", "", normalized)
    return int(digits) if digits else None


def _as_markdown(html: str) -> str:
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")

    def render(node: Any) -> str:
        if isinstance(node, NavigableString):
            return str(node).replace("\xa0", " ")
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()

        if name in {"script", "style"}:
            return ""
        if name == "br":
            return "\n"
        if name == "img":
            src = (node.get("src") or "").strip()
            alt = _clean_text(node.get("alt"))
            return f"![{alt}]({src})" if src else ""
        if name == "a":
            text = "".join(render(child) for child in node.children).strip()
            href = (node.get("href") or "").strip()
            if href and text:
                return f"[{text}]({href})"
            return text
        if name in {"strong", "b"}:
            content = "".join(render(child) for child in node.children).strip()
            return f"**{content}**" if content else ""
        if name in {"em", "i"}:
            content = "".join(render(child) for child in node.children).strip()
            return f"*{content}*" if content else ""
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(name[1])
            content = "".join(render(child) for child in node.children).strip()
            return f"{'#' * level} {content}\n\n" if content else ""
        if name == "li":
            content = "".join(render(child) for child in node.children).strip()
            return f"- {content}\n" if content else ""
        if name in {"ul", "ol"}:
            content = "".join(render(child) for child in node.children)
            return f"{content}\n" if content else ""
        if name in {"p", "div", "section", "article", "blockquote"}:
            content = "".join(render(child) for child in node.children).strip()
            return f"{content}\n\n" if content else ""

        return "".join(render(child) for child in node.children)

    rendered = "".join(render(child) for child in soup.contents)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip()


def _load_blogposting_jsonld(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue

        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@type") == "BlogPosting":
                return entry
    return {}


def _extract_post(soup: BeautifulSoup, jsonld: dict[str, Any]) -> dict[str, Any]:
    post_box = soup.select_one("div.post-box")
    content_wrapper = post_box.select_one("div.content-wrapper") if post_box else None

    title = ""
    body_html = ""
    if content_wrapper:
        body_fragment = BeautifulSoup(str(content_wrapper), "html.parser")
        title_element = body_fragment.select_one("h2.post-title")
        if title_element:
            title = _clean_text(title_element.get_text(" ", strip=True))
            title_element.decompose()
        body_html = body_fragment.decode_contents().strip()

    if not title:
        title = _clean_text(jsonld.get("headline")) or _clean_text(
            soup.select_one("meta[property='og:title']") and soup.select_one("meta[property='og:title']").get("content")
        )

    post_info = post_box.select_one("div.post-info") if post_box else None
    author = _clean_text(post_info.select_one(".author-name").get_text(" ", strip=True)) if post_info and post_info.select_one(".author-name") else ""
    date_posted_shamsi = (
        _clean_text(post_info.select_one(".post-date").get_text(" ", strip=True))
        if post_info and post_info.select_one(".post-date")
        else ""
    )
    like_text = post_box.select_one("[id^='post-like-count-']").get_text(" ", strip=True) if post_box and post_box.select_one("[id^='post-like-count-']") else ""
    likes = _to_int(like_text)
    is_pinned = bool(post_box.select_one(".pin-icon")) if post_box else False

    canonical = soup.select_one("link[rel='canonical']")
    canonical_url = canonical.get("href", "").strip() if canonical else ""
    date_posted = _clean_text(jsonld.get("datePublished")) or _clean_text(jsonld.get("dateCreated"))

    images: list[dict[str, str]] = []
    if content_wrapper:
        for image in content_wrapper.select("img[src]"):
            images.append(
                {
                    "src": image.get("src", "").strip(),
                    "alt": _clean_text(image.get("alt")),
                }
            )

    return {
        "title": title,
        "author": author or _clean_text(jsonld.get("author", {}).get("name") if isinstance(jsonld.get("author"), dict) else ""),
        "body_markdown": _as_markdown(body_html),
        "body_html": body_html,
        "date_posted_shamsi": date_posted_shamsi,
        "date_posted": date_posted,
        "likes": likes,
        "is_pinned": is_pinned,
        "images": images,
        "canonical_url": canonical_url,
    }


def _extract_comments(soup: BeautifulSoup) -> dict[str, Any]:
    comments_box = soup.select_one("div.comments-box#comments") or soup.select_one("div.comments-box")
    if not comments_box:
        return {"count": 0, "items": []}

    count_text = comments_box.select_one(".comments-title .counter")
    declared_count = _to_int(count_text.get_text(" ", strip=True)) if count_text else 0
    items: list[dict[str, Any]] = []
    last_comment_id: int | None = None

    for order, node in enumerate(comments_box.select("div.comment"), start=1):
        classes = node.get("class", [])
        is_reply = "reply" in classes

        comment_id: int | None = None
        if node.get("id", "").startswith("comment-"):
            comment_id = _to_int(node.get("id", ""))

        content_node = node.select_one(".comment-content")
        content_html = content_node.decode_contents().strip() if content_node else ""
        plus_text = node.select_one("[id^='comment-rate-plus-count-']")
        minus_text = node.select_one("[id^='comment-rate-minus-count-']")

        if is_reply:
            items.append(
                {
                    "id": comment_id,
                    "type": "reply",
                    "parent_comment_id": last_comment_id,
                    "content_markdown": _as_markdown(content_html),
                    "content_html": content_html,
                    "likes": _to_int(plus_text.get_text(" ", strip=True)) if plus_text else None,
                    "dislikes": _to_int(minus_text.get_text(" ", strip=True)) if minus_text else None,
                    "order": order,
                }
            )
            continue

        author_name = node.select_one(".author-name")
        author_website = node.select_one(".author-website")
        avatar = node.select_one(".author-avatar img")
        date_node = node.select_one(".comment-date")
        author_text = _clean_text(author_name.get_text(" ", strip=True)) if author_name else ""
        date_text = _clean_text(date_node.get_text(" ", strip=True)) if date_node else ""
        content_markdown = _as_markdown(content_html)
        likes = _to_int(plus_text.get_text(" ", strip=True)) if plus_text else None
        dislikes = _to_int(minus_text.get_text(" ", strip=True)) if minus_text else None

        # Ignore placeholder nodes that are not real comments.
        if not any([comment_id, author_text, date_text, content_markdown, likes, dislikes]):
            continue

        item = {
            "id": comment_id,
            "type": "comment",
            "author": author_text,
            "author_website": author_website.get("href", "").strip() if author_website else "",
            "author_avatar": avatar.get("src", "").strip() if avatar else "",
            "date_posted_shamsi": date_text,
            "content_markdown": content_markdown,
            "content_html": content_html,
            "likes": likes,
            "dislikes": dislikes,
            "order": order,
        }
        items.append(item)
        last_comment_id = comment_id

    return {
        "count": declared_count if declared_count is not None else len(items),
        "items": items,
    }


def _parse_html_file(path: Path) -> dict[str, Any]:
    html = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    jsonld = _load_blogposting_jsonld(soup)
    post = _extract_post(soup, jsonld)
    comments = _extract_comments(soup)

    meta_description = soup.select_one("meta[name='description']")
    og_site_name = soup.select_one("meta[property='og:site_name']")
    blog_title = _clean_text(soup.select_one(".blog-title a").get_text(" ", strip=True)) if soup.select_one(".blog-title a") else ""
    blog_description = _clean_text(soup.select_one(".blog-description").get_text(" ", strip=True)) if soup.select_one(".blog-description") else ""

    canonical_url = post.get("canonical_url") or _clean_text(jsonld.get("url"))
    slug = ""
    if canonical_url:
        slug = urlparse(canonical_url).path.strip("/")

    payload = {
        "source_file": str(path.relative_to(REPO_ROOT)),
        "post": post,
        "comments": comments,
        "metadata": {
            "slug": slug,
            "site_name": _clean_text(og_site_name.get("content")) if og_site_name else "",
            "blog_title": blog_title,
            "blog_description": blog_description,
            "description": _clean_text(meta_description.get("content")) if meta_description else "",
            "jsonld": jsonld,
        },
    }
    return payload


def _iter_html_files(out_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in out_root.rglob("*.html"):
        if "json" in path.parts:
            continue
        files.append(path)
    return sorted(files)


def _output_path_for(html_path: Path) -> Path:
    return html_path.parent / "json" / f"{html_path.stem}.json"


def convert(out_root: Path) -> tuple[int, int]:
    html_files = _iter_html_files(out_root)
    converted = 0
    failed = 0

    for html_file in html_files:
        try:
            payload = _parse_html_file(html_file)
            output = _output_path_for(html_file)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            converted += 1
            logging.info("Converted %s -> %s", html_file.relative_to(REPO_ROOT), output.relative_to(REPO_ROOT))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logging.warning("Failed to convert %s: %s", html_file, exc)

    return converted, failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert crawled HTML files in out/* to JSON files in out/*/json.")
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help=f"Root directory containing crawled HTML files (default: {DEFAULT_OUT_ROOT})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out_root = args.out_root.resolve()
    if not out_root.exists():
        raise SystemExit(f"Directory does not exist: {out_root}")

    converted, failed = convert(out_root)
    logging.info("Conversion finished. converted=%d failed=%d", converted, failed)


if __name__ == "__main__":
    main()
