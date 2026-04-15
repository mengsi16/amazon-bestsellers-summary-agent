#!/usr/bin/env python3
"""
Markdown-first batch pipeline for Amazon product chunking.

Pipeline:
1) Convert product HTML -> canonical markdown
2) Semantic chunking into ppd/customer_reviews/product_details/aplus/misc
3) Generate extracted markdown files for downstream analyst agents
4) Build global manifest
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from chunker.markdown_semantic_chunker import run as run_semantic_chunk
from chunker.markitdown_batch_convert import run as run_markitdown_convert


PRODUCT_DIR_RE = re.compile(r"^(\d{3})_([A-Z0-9]{10})$")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
BLOCKS = ("ppd", "customer_reviews", "product_details", "aplus")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _first_non_empty(*paths: Path) -> tuple[Path | None, str]:
    for path in paths:
        if path.exists():
            text = _read_text(path).strip()
            if text:
                return path, text
    return None, ""


def _extract_image_urls(text: str) -> list[str]:
    urls = []
    for raw in URL_RE.findall(text):
        cleaned = raw.rstrip(")].,;\"")
        if "amazon" in cleaned.lower() and cleaned not in urls:
            urls.append(cleaned)
    return urls


def _render_ppd(text: str) -> str:
    image_urls = _extract_image_urls(text)
    lines = ["# PPD Extracted", "", "## Core", "", "- Source: markdown_semantic_chunker", ""]
    lines.extend(["## Image Assets", ""])
    if image_urls:
        for url in image_urls[:30]:
            lines.append(f"- {url}")
    else:
        lines.append("- N/A")
    lines.extend(["", "## Raw PPD Context", "", text, ""])
    return "\n".join(lines).strip() + "\n"


def _render_generic(title: str, text: str) -> str:
    return f"# {title}\n\n## Raw Context\n\n{text}\n"


def _render_block_extract(block: str, text: str) -> str:
    if block == "ppd":
        return _render_ppd(text)
    if block == "customer_reviews":
        return _render_generic("Customer Reviews Extracted", text)
    if block == "product_details":
        return _render_generic("Product Details Extracted", text)
    if block == "aplus":
        return _render_generic("A+ Extracted", text)
    return _render_generic(f"{block} Extracted", text)


def _extract_block(product_dir: Path, block: str, skip_extracted: bool) -> tuple[str, str]:
    extract_dir = product_dir / block / "extract"
    out_path = extract_dir / f"{block}_extracted.md"
    if skip_extracted and out_path.exists() and out_path.stat().st_size > 0:
        return "SUCCESS", str(out_path)

    raw_md = product_dir / block / "raw" / f"{block}.md"
    raw_html = product_dir / block / "raw" / f"{block}.html"
    source_path, text = _first_non_empty(raw_md, raw_html)

    if source_path is None:
        return "SKIPPED", "N/A"

    extract_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(_render_block_extract(block, text), encoding="utf-8")
    return "SUCCESS", str(out_path)


def _build_product_manifest(product_dir: Path, skip_extracted: bool) -> dict:
    manifest_path = product_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(_read_text(manifest_path))
    else:
        manifest = {"product_dir": product_dir.name, "blocks": {}}

    for block in BLOCKS:
        block_state = dict(manifest.get("blocks", {}).get(block, {}))
        chunk_status = block_state.get("chunk", "NOT_FOUND")

        if chunk_status != "SUCCESS":
            block_state["extract"] = "SKIPPED"
            block_state["extract_path"] = "N/A"
        else:
            extract_status, extract_path = _extract_block(product_dir, block, skip_extracted)
            block_state["extract"] = extract_status
            block_state["extract_path"] = extract_path

        manifest.setdefault("blocks", {})[block] = block_state

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _to_global_row(product_manifest: dict) -> dict:
    name = product_manifest.get("product_dir", "")
    match = PRODUCT_DIR_RE.match(name)
    rank = match.group(1) if match else "N/A"
    asin = match.group(2) if match else "N/A"

    blocks = {}
    for block in BLOCKS:
        data = product_manifest.get("blocks", {}).get(block, {})
        blocks[block] = {
            "chunk": data.get("chunk", "NOT_FOUND"),
            "extract": data.get("extract", "SKIPPED"),
        }

    extract_failed = any(info["extract"] == "FAILED" for info in blocks.values())
    status = "FAILED" if extract_failed else "SUCCESS"

    return {
        "rank": rank,
        "asin": asin,
        "dir": name,
        "status": status,
        "blocks": blocks,
    }


def _write_global_manifest(chunks_dir: Path, rows: list[dict]) -> Path:
    global_manifest = {
        "total": len(rows),
        "success": sum(1 for row in rows if row["status"] == "SUCCESS"),
        "failed": sum(1 for row in rows if row["status"] == "FAILED"),
        "products": rows,
    }
    path = chunks_dir / "global_manifest.json"
    path.write_text(json.dumps(global_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_pipeline(raw_dir: Path, out_dir: Path, limit: int | None, skip_extracted: bool) -> Path:
    run_markitdown_convert(raw_dir, out_dir, limit)
    run_semantic_chunk(out_dir, limit)

    product_dirs = sorted(
        path for path in out_dir.iterdir() if path.is_dir() and PRODUCT_DIR_RE.match(path.name)
    )
    if limit is not None:
        product_dirs = product_dirs[:limit]

    rows = []
    for product_dir in product_dirs:
        product_manifest = _build_product_manifest(product_dir, skip_extracted)
        rows.append(_to_global_row(product_manifest))

    return _write_global_manifest(out_dir, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run markdown-first chunk/extract pipeline")
    parser.add_argument("raw_dir", type=Path, help="Directory containing product_XXXX_ASIN.html files")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output chunks directory")
    parser.add_argument("--limit", type=int, default=None, help="Process first N products")
    parser.add_argument(
        "--skip-extracted",
        action="store_true",
        help="Skip re-generating extracted markdown when output already exists",
    )
    args = parser.parse_args()

    global_manifest_path = run_pipeline(args.raw_dir, args.out_dir, args.limit, args.skip_extracted)
    print(f"Batch pipeline complete: {global_manifest_path}")


if __name__ == "__main__":
    main()
