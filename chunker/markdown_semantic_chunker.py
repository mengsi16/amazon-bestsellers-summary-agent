#!/usr/bin/env python3
"""
Semantic chunker for canonical Markdown generated from product HTML.

Input layout:
    {chunks_dir}/{rank}_{asin}/source/canonical.md

Output layout per product:
    {chunks_dir}/{rank}_{asin}/ppd/raw/ppd.md
    {chunks_dir}/{rank}_{asin}/customer_reviews/raw/customer_reviews.md
    {chunks_dir}/{rank}_{asin}/product_details/raw/product_details.md
    {chunks_dir}/{rank}_{asin}/aplus/raw/aplus.md
    {chunks_dir}/{rank}_{asin}/misc/raw/misc.md
    {chunks_dir}/{rank}_{asin}/manifest.json
"""

from __future__ import annotations

import argparse
import json
import re
from html import escape
from dataclasses import dataclass
from pathlib import Path


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


BLOCK_KEYWORDS = {
    "ppd": ["about this item", "feature bullets", "price", "buy", "title", "variant", "overview"],
    "customer_reviews": ["customer reviews", "ratings", "review", "top reviews"],
    "product_details": ["product details", "product information", "item details", "technical details"],
    "aplus": ["a+", "brand story", "from the manufacturer", "comparison table"],
}


@dataclass(frozen=True)
class Section:
    title: str
    body: str


def parse_sections(markdown: str) -> list[Section]:
    sections: list[Section] = []
    current_title = "preamble"
    current_lines: list[str] = []

    for line in markdown.splitlines():
        match = HEADING_RE.match(line)
        if match:
            if current_lines:
                sections.append(Section(title=current_title, body="\n".join(current_lines).strip()))
            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(Section(title=current_title, body="\n".join(current_lines).strip()))

    return sections


def classify_section(section: Section) -> str:
    text = f"{section.title}\n{section.body}".lower()
    for block, keywords in BLOCK_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return block
    return "misc"


def write_block(product_dir: Path, block: str, content: str) -> dict:
    block_dir = product_dir / block / "raw"
    block_dir.mkdir(parents=True, exist_ok=True)
    md_path = block_dir / f"{block}.md"
    html_path = block_dir / f"{block}.html"
    md_path.write_text(content, encoding="utf-8")

    # Keep a compatibility HTML file for downstream steps that still read raw HTML.
    html_wrapper = "\n".join([
        "<!doctype html>",
        "<html>",
        "<head><meta charset=\"utf-8\"></head>",
        "<body><pre>",
        escape(content),
        "</pre></body>",
        "</html>",
    ])
    html_path.write_text(html_wrapper, encoding="utf-8")

    return {
        "chunk": "SUCCESS",
        "path": str(md_path),
        "compat_html_path": str(html_path),
    }


def chunk_product(product_dir: Path) -> dict:
    source_md = product_dir / "source" / "canonical.md"
    if not source_md.exists():
        return {
            "product": product_dir.name,
            "status": "SKIPPED",
            "reason": "canonical_markdown_missing",
        }

    text = source_md.read_text(encoding="utf-8", errors="ignore")
    sections = parse_sections(text)

    bucket: dict[str, list[str]] = {"ppd": [], "customer_reviews": [], "product_details": [], "aplus": [], "misc": []}
    for section in sections:
        block = classify_section(section)
        bucket[block].append(section.body)

    manifest_blocks = {}
    for block, chunks in bucket.items():
        if chunks:
            joined = "\n\n".join(chunks).strip()
            manifest_blocks[block] = write_block(product_dir, block, joined)
        else:
            manifest_blocks[block] = {"chunk": "NOT_FOUND", "path": "N/A"}

    manifest = {
        "product_dir": product_dir.name,
        "source_markdown": str(source_md),
        "blocks": manifest_blocks,
    }

    manifest_path = product_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "product": product_dir.name,
        "status": "SUCCESS",
        "manifest": str(manifest_path),
    }


def run(chunks_dir: Path, limit: int | None = None) -> Path:
    product_dirs = sorted([path for path in chunks_dir.iterdir() if path.is_dir() and re.match(r"^\d{3}_[A-Z0-9]{10}$", path.name)])
    if limit is not None:
        product_dirs = product_dirs[:limit]

    results = [chunk_product(product_dir) for product_dir in product_dirs]

    summary = {
        "chunks_dir": str(chunks_dir),
        "total": len(results),
        "success": sum(1 for row in results if row["status"] == "SUCCESS"),
        "skipped": sum(1 for row in results if row["status"] == "SKIPPED"),
        "products": results,
    }

    summary_path = chunks_dir / "semantic_chunk_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic chunk canonical markdown into product blocks")
    parser.add_argument("--chunks-dir", type=Path, required=True, help="Chunks root containing {rank}_{asin} directories")
    parser.add_argument("--limit", type=int, default=None, help="Process first N products only")
    args = parser.parse_args()

    summary_path = run(args.chunks_dir, args.limit)
    print(f"Semantic chunking complete: {summary_path}")


if __name__ == "__main__":
    main()
