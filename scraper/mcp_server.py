"""MCP Server for Amazon Bestsellers Scraper.

Exposes two tools for Claude-Code:
  1. crawl_bestseller_list  — Phase 1: crawl category pages, discover Top 50 products
  2. crawl_product_details  — Phase 2: crawl product detail pages (async concurrent)

Usage (stdio mode):
    python scraper/mcp_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from raw_amazon_spider import (
    CrawlConfig,
    RawAmazonSpider,
)

LOGGER = logging.getLogger("mcp_amazon_scraper")

mcp = FastMCP(
    "Amazon Bestsellers Scraper",
    instructions=(
        "Crawl Amazon Bestsellers category pages and product detail pages. "
        "IMPORTANT: output_dir MUST be an absolute path provided by the orchestrator "
        "(e.g. {workspace}/raw_html_output). Do NOT use the default relative path."
    ),
)

WINDOWS_ROOTED_DRIVE_SEGMENT_RE = re.compile(r"^[\\/](?P<drive>[A-Za-z])[\\/](?P<rest>.*)$")
WINDOWS_MISSING_COLON_RE = re.compile(r"^(?P<drive>[A-Za-z])[\\/](?P<rest>.*)$")
WINDOWS_DRIVE_RELATIVE_RE = re.compile(r"^(?P<drive>[A-Za-z]):(?P<rest>[^\\/].*)$")


def _coerce_windows_absolute_path(raw_path: str) -> str:
    """Fix common malformed Windows absolute paths produced by agents.

    Examples:
      /e/Internship/...   -> E:/Internship/...
      e\\Internship\\... -> E:/Internship/...
      e:Internship\\...  -> E:/Internship/...
    """
    candidate = raw_path.strip().strip('"').strip("'")
    if not candidate or os.name != "nt":
        return candidate

    current_drive = Path.cwd().drive.rstrip(":").upper()

    for pattern in (
        WINDOWS_ROOTED_DRIVE_SEGMENT_RE,
        WINDOWS_MISSING_COLON_RE,
        WINDOWS_DRIVE_RELATIVE_RE,
    ):
        match = pattern.match(candidate)
        if not match:
            continue
        drive = match.group("drive").upper()
        if drive != current_drive:
            # Avoid coercing malformed paths that do not target the current drive.
            return candidate
        rest = match.group("rest").lstrip("\\/").replace("\\", "/")
        return f"{drive}:/{rest}" if rest else f"{drive}:/"

    return candidate


def _is_default_relative_output_dir(path_value: str) -> bool:
    """Return True for allowed default relative forms of raw_html_output."""
    normalized = path_value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    return normalized == "raw_html_output"


def _build_config(
    category_url: str = "",
    output_dir: str = "raw_html_output",
    max_category_pages: int = 1,
    max_products: int | None = None,
    timeout_ms: int = 90000,
    wait_ms: int = 2500,
    delay_ms: int = 3500,
    retries_per_fetcher: int = 2,
    headless: bool = True,
    prefer_stealth: bool = True,
    solve_cloudflare: bool = False,
    proxy: str | None = None,
    scroll_category: bool = True,
    scroll_pause_ms: int = 1500,
) -> CrawlConfig:
    """Build a CrawlConfig from tool parameters.

    WARNING: output_dir should be an absolute path from the orchestrator.
    If malformed or relative paths are passed, we either normalize known
    Windows mistakes or fail fast to avoid writing into unexpected directories.
    """
    coerced_output_dir = _coerce_windows_absolute_path(output_dir)
    if coerced_output_dir != output_dir:
        LOGGER.warning(
            "Normalized output_dir from '%s' to '%s' to fix Windows drive formatting.",
            output_dir,
            coerced_output_dir,
        )

    output_path = Path(coerced_output_dir)
    if not output_path.is_absolute():
        if _is_default_relative_output_dir(coerced_output_dir):
            resolved = output_path.resolve()
            LOGGER.warning(
                "output_dir '%s' is relative — resolved to '%s'. "
                "Orchestrator should pass an absolute path like {workspace}/raw_html_output.",
                output_dir,
                resolved,
            )
        else:
            raise ValueError(
                "output_dir must be an absolute path. "
                f"Received: '{output_dir}'. "
                "On Windows use 'E:/path' or 'E:\\\\path'. "
                "Common malformed forms like '/e/path' and 'e\\path' are auto-corrected; "
                "other relative paths are rejected."
            )
    else:
        resolved = output_path.resolve()

    return CrawlConfig(
        category_url=category_url,
        output_dir=resolved,
        max_category_pages=max_category_pages,
        max_products=max_products,
        timeout_ms=timeout_ms,
        wait_ms=wait_ms,
        delay_ms=delay_ms,
        retries_per_fetcher=retries_per_fetcher,
        headless=headless,
        prefer_stealth=prefer_stealth,
        solve_cloudflare=solve_cloudflare,
        capture_xhr_pattern=".*",
        useragent=None,
        proxy=proxy,
        scroll_category=scroll_category,
        scroll_pause_ms=scroll_pause_ms,
    )


@mcp.tool()
async def crawl_bestseller_list(
    category_url: str,
    output_dir: str = "raw_html_output",
    max_category_pages: int = 1,
    delay_ms: int = 3500,
    headless: bool = True,
    scroll_category: bool = True,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Crawl Amazon Bestsellers category pages and discover Top 50 product links.

    This is Phase 1 of the two-phase crawling process. It visits the
    bestseller listing page(s), scrolls to trigger lazy-loaded products,
    and returns the discovered product URLs/ASINs.

    Args:
        category_url: Amazon Bestsellers category URL
            (e.g. "https://www.amazon.com/gp/bestsellers/home-garden/3744541")
        output_dir: **Absolute path** to the workspace raw_html_output directory,
            e.g. "{workspace}/raw_html_output". The orchestrator MUST provide this.
            Falls back to "raw_html_output" (relative) if not specified.
        max_category_pages: Max category pages to crawl (default: 1)
        delay_ms: Delay between requests in ms (default: 3500)
        headless: Run browser in headless mode (default: True)
        scroll_category: Auto-scroll to trigger lazy-loaded products (default: True)
        proxy: Optional proxy string

    Returns:
        Dict with run_id, discovered_products list, stats, and output paths.
        Use run_id and discovered_products to call crawl_product_details.
    """
    config = _build_config(
        category_url=category_url,
        output_dir=output_dir,
        max_category_pages=max_category_pages,
        delay_ms=delay_ms,
        headless=headless,
        scroll_category=scroll_category,
        proxy=proxy,
    )
    spider = RawAmazonSpider(config)
    # Run sync Playwright code in a thread pool to avoid
    # "Playwright Sync API inside asyncio loop" error.
    result = await asyncio.to_thread(spider.crawl_category_pages)

    return {
        "run_id": result["run_id"],
        "product_count": len(result["discovered_products"]),
        "products": [
            {
                "canonical_url": p["canonical_url"],
                "asin": p.get("asin"),
                "discovered_order": p.get("discovered_order"),
            }
            for p in result["discovered_products"]
        ],
        "stats": result["stats"],
        "paths": result["paths"],
    }


@mcp.tool()
async def crawl_product_details(
    run_id: str,
    product_urls: list[str],
    output_dir: str = "raw_html_output",
    max_concurrency: int = 3,
    delay_ms: int = 3500,
    headless: bool = True,
    solve_cloudflare: bool = False,
    proxy: str | None = None,
) -> dict[str, Any]:
    """Crawl Amazon product detail pages with async concurrency.

    This is Phase 2 of the two-phase crawling process. Pass product URLs
    discovered by crawl_bestseller_list. Supports single or batch crawling:
    pass 1 URL for single execution, or multiple URLs for concurrent crawling.

    Args:
        run_id: Run ID from crawl_bestseller_list (writes into same output dir)
        product_urls: List of product URLs to crawl
            (e.g. ["https://www.amazon.com/dp/B0DRNRC5H5"])
        output_dir: **Absolute path** to the workspace raw_html_output directory,
            e.g. "{workspace}/raw_html_output". The orchestrator MUST provide this.
            Falls back to "raw_html_output" (relative) if not specified.
        max_concurrency: Max concurrent browser tabs (default: 3)
        delay_ms: Delay between requests in ms (default: 3500)
        headless: Run browser in headless mode (default: True)
        solve_cloudflare: Enable Cloudflare bypass (default: False)
        proxy: Optional proxy string

    Returns:
        Dict with results list (one per product) and stats summary.
    """
    config = _build_config(
        output_dir=output_dir,
        delay_ms=delay_ms,
        headless=headless,
        solve_cloudflare=solve_cloudflare,
        proxy=proxy,
    )
    spider = RawAmazonSpider(config, run_id=run_id)

    product_list = [
        {"canonical_url": url, "asin": _extract_asin_from_url(url)}
        for url in product_urls
    ]

    result = await spider.crawl_product_details(product_list, max_concurrency)

    return {
        "stats": result["stats"],
        "results": [
            {
                "url": r.get("requested_url"),
                "asin": r.get("asin"),
                "valid": r.get("valid_product_page"),
                "html_size": r.get("html_size"),
                "html_file": r.get("html_file"),
                "error": r.get("error"),
            }
            for r in result["results"]
        ],
    }


def _extract_asin_from_url(url: str) -> str | None:
    """Extract ASIN from an Amazon product URL."""
    import re

    match = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", url, re.IGNORECASE)
    return match.group(1).upper() if match else None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    mcp.run(transport="stdio")
