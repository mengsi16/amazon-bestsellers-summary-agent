#!/usr/bin/env python3
"""
Batch convert Amazon raw HTML product pages to canonical Markdown with MarkItDown.

Input filenames are expected to follow:
    product_0001_B0XXXXX.html

Output layout:
    {out_dir}/{rank}_{asin}/source/raw.html
    {out_dir}/{rank}_{asin}/source/canonical.md
    {out_dir}/markdown_manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown


PRODUCT_FILE_RE = re.compile(r"^product_(\d{4})_([A-Z0-9]{10})\.html$", re.IGNORECASE)


def parse_name(path: Path) -> Optional[tuple[str, str]]:
    match = PRODUCT_FILE_RE.match(path.name)
    if not match:
        return None
    rank = f"{int(match.group(1)):03d}"
    asin = match.group(2).upper()
    return rank, asin


def convert_one(md: MarkItDown, html_path: Path, out_dir: Path) -> dict:
    parsed = parse_name(html_path)
    if parsed is None:
        return {
            "file": str(html_path),
            "status": "SKIPPED",
            "reason": "filename_pattern_mismatch",
        }

    rank, asin = parsed
    product_dir = out_dir / f"{rank}_{asin}" / "source"
    product_dir.mkdir(parents=True, exist_ok=True)

    raw_copy = product_dir / "raw.html"
    raw_copy.write_text(html_path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")

    md_path = product_dir / "canonical.md"

    try:
        result = md.convert(str(html_path))
        md_path.write_text(result.text_content or "", encoding="utf-8")
        return {
            "rank": rank,
            "asin": asin,
            "source": str(html_path),
            "markdown": str(md_path),
            "status": "SUCCESS",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "rank": rank,
            "asin": asin,
            "source": str(html_path),
            "status": "FAILED",
            "reason": str(exc),
        }


def run(input_dir: Path, out_dir: Path, limit: int | None = None) -> Path:
    html_files = sorted(input_dir.glob("product_*_*.html"))
    if limit is not None:
        html_files = html_files[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    md = MarkItDown(enable_plugins=False)

    rows = [convert_one(md, html, out_dir) for html in html_files]

    success = sum(1 for row in rows if row.get("status") == "SUCCESS")
    failed = sum(1 for row in rows if row.get("status") == "FAILED")
    skipped = sum(1 for row in rows if row.get("status") == "SKIPPED")

    manifest = {
        "input_dir": str(input_dir),
        "out_dir": str(out_dir),
        "total": len(rows),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "products": rows,
    }

    manifest_path = out_dir / "markdown_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert product HTML to canonical Markdown")
    parser.add_argument("input_dir", type=Path, help="Directory containing product_XXXX_ASIN.html files")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output chunks directory")
    parser.add_argument("--limit", type=int, default=None, help="Process first N files only")
    args = parser.parse_args()

    manifest_path = run(args.input_dir, args.out_dir, args.limit)
    print(f"Markdown conversion complete: {manifest_path}")


if __name__ == "__main__":
    main()
