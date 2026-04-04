# Amazon Bestsellers Raw HTML Scraper

## Overview

A Python command-line crawler that archives **raw HTML** from Amazon Bestsellers category pages and their product detail pages. It does **not** parse or extract structured data — its sole purpose is to reliably download and persist the full rendered HTML (plus request metadata) so that downstream tools can process the pages offline.

### How It Works (Two-Phase Crawl)

1. **Phase 1 — Category Listing Pages**
   - Fetches the given Amazon Bestsellers category URL (e.g. `https://www.amazon.com/gp/bestsellers/home-garden/3744541`).
   - Extracts all product links (ASIN-based `/dp/` URLs) from the page.
   - Follows pagination links within the same category (controlled by `--max-category-pages`).

2. **Phase 2 — Product Detail Pages**
   - Takes the discovered product URLs from Phase 1.
   - Crawls each product's detail page individually (controlled by `--max-products`).
   - Saves the full rendered HTML of each product page.

All fetched pages are saved as **raw `.html` files**. Request/response metadata (headers, cookies, status codes, redirect history, etc.) and discovered product links are recorded as **JSONL** files for traceability.

### Key Features

| Feature | Description |
|---|---|
| **Raw HTML Archiving** | Saves the full browser-rendered HTML of every page — no lossy parsing at crawl time. |
| **Two-Phase Crawl** | First collects product URLs from Bestsellers listing pages, then crawls each product detail page. |
| **Dual Fetcher with Fallback** | Uses `scrapling` library's `DynamicFetcher` and `StealthyFetcher`; automatically falls back if the primary fetcher is blocked. |
| **Anti-Bot Detection** | Detects CAPTCHA / robot-check pages and flags them as `blocked` in metadata. |
| **Auto-Scroll for Lazy Loading** | Automatically scrolls category pages to trigger Amazon's lazy-loaded XHR, ensuring all Top 50 products are discovered (not just the initial ~30). |
| **XHR Capture** | Optionally captures all XHR/fetch network requests made during page load (including lazy-load responses). |
| **Category Pagination** | Follows `?pg=` pagination within the same Bestsellers category path. |
| **Structured Metadata** | Logs every request to `requests.jsonl` with status, headers, cookies, redirect history, and timing. |
| **Proxy Support** | Optional proxy for all requests (`--proxy`). |
| **Request Throttling** | Configurable delay between requests (`--delay-ms`) to reduce detection risk. |
| **Headless / Headful** | Run the browser headless (default) or headful for debugging (`--headful`). |
| **CLI Driven** | All options via command-line arguments; no config files needed. |

---

## Project Structure

```
Amazon-Bestsellers-Scraper/
├── src/
│   ├── raw_amazon_spider.py   # Main crawler script (entry point)
│   ├── mcp_server.py          # MCP Server for Claude-Code integration
│   ├── requirements.txt       # Python dependencies
│   └── Makefile               # Shortcut commands (setup, fmt)
├── raw_html_output/           # Crawl output root (git-ignored)
│   └── <run_id>/              # One folder per run, e.g. 20260402T011314Z
│       ├── categories/        # Raw HTML of Bestsellers listing pages
│       ├── products/          # Raw HTML of product detail pages
│       ├── xhr/               # Captured XHR responses (JSONL)
│       └── meta/
│           ├── requests.jsonl       # Full request/response log
│           ├── product_links.jsonl  # All discovered product URLs + ASINs
│           └── crawl_summary.json   # Run config, stats, output paths
└── README.md
```

---

## Installation

```bash
# 1. Create & activate a virtual environment
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 2. Install dependencies
pip install -r src/requirements.txt

# 3. Install the Chromium browser for Playwright (required by scrapling)
python -m playwright install chromium
```

### Dependencies

| Package | Purpose |
|---|---|
| `scrapling[fetchers]==0.4.3` | Browser-based fetching (DynamicFetcher / StealthyFetcher) |
| `playwright==1.47.0` | Headless Chromium automation (used by scrapling) |
| `python-dotenv==1.0.1` | Environment variable loading |

---

## Usage

Recommended entry point: `main.py` at the project root.

It runs the full pipeline in one command:

1. scraper
2. chunker
3. extraction + global manifest build

### Unified Entry Point (Recommended)

```bash
# run from project root
python main.py "https://www.amazon.com/gp/bestsellers/home-garden/3744541/ref=pd_zg_hrsr_home-garden"
```

Common options:

```bash
# set explicit run id
python main.py "<category_url>" --run-id 20260402T035937Z

# rebuild chunk/extract/manifest only (skip network crawl)
python main.py "<category_url>" --run-id 20260402T035937Z --skip-scrape

# rebuild organized tree + run manifest only
python main.py "<category_url>" --run-id 20260402T035937Z --skip-scrape --skip-chunk

# limit crawl size
python main.py "<category_url>" --max-category-pages 1 --max-products 50
```

### Low-Level Entrypoint (Advanced)

If you need to debug crawler-only behavior, you can still use `raw_amazon_spider.py` directly. All options are passed via CLI arguments.

### Basic Example

```bash
# Crawl the "Vacuum Storage Bags" Bestsellers category
# Fetch up to 2 category pages, then crawl up to 50 product detail pages
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --max-category-pages 2 \
  --max-products 50
```

### Minimal Test Run

```bash
# Quick test: 1 category page, 1 product page
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --max-category-pages 1 \
  --max-products 1
```

### Full Options

```
usage: raw_amazon_spider.py [-h] --category-url CATEGORY_URL
                            [--output-dir OUTPUT_DIR]
                            [--max-category-pages N]
                            [--max-products N]
                            [--timeout-ms MS]
                            [--wait-ms MS]
                            [--delay-ms MS]
                            [--retries-per-fetcher N]
                            [--headless | --headful]
                            [--prefer-stealth]
                            [--solve-cloudflare]
                            [--capture-xhr-pattern REGEX | --no-capture-xhr]
                            [--useragent UA]
                            [--proxy PROXY]
                            [--log-level {DEBUG,INFO,WARNING,ERROR}]
```

| Argument | Default | Description |
|---|---|---|
| `--category-url` | *(required)* | Amazon Bestsellers category URL to crawl. |
| `--output-dir` | `raw_html_output` | Root directory for crawl output. |
| `--max-category-pages` | `1` | Max number of Bestsellers listing pages to crawl (pagination). |
| `--max-products` | `None` (all) | Max product detail pages to crawl. `None` = crawl all discovered. |
| `--timeout-ms` | `90000` | Browser page load timeout in milliseconds. |
| `--wait-ms` | `2500` | Extra wait after page settles (ms). |
| `--delay-ms` | `1200` | Delay between consecutive requests (ms). |
| `--retries-per-fetcher` | `2` | Retry attempts per fetcher before falling back. |
| `--headless` / `--headful` | `--headless` | Run browser headless or with visible UI. |
| `--prefer-stealth` | `false` | Try `StealthyFetcher` before `DynamicFetcher`. |
| `--solve-cloudflare` | `false` | Enable Cloudflare challenge solving (stealth fetcher only). |
| `--capture-xhr-pattern` | `.*` (all) | Regex to filter captured XHR requests. |
| `--no-capture-xhr` | — | Disable XHR capture entirely. |
| `--useragent` | `None` | Custom User-Agent string. |
| `--proxy` | `None` | Proxy URL (e.g. `http://user:pass@host:port`). |
| `--no-scroll` | *(off)* | Disable auto-scrolling on category pages. |
| `--scroll-pause-ms` | `1500` | Pause between scroll steps in ms. |
| `--log-level` | `INFO` | Logging verbosity. |

---

## Chunk Extraction + Manifest Sync

After `static_chunker.py` generates block files and `manifest.json`, you can run three focused extractors to generate markdown outputs.

### Single Product: Run Three Extractors

```bash
python chunker/customer_reviews_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/customer_reviews.html
python chunker/product_details_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/product_details.html
python chunker/ppd_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/ppd.html
```

These extractors automatically update `manifest.json` entries under `blocks`:
- `customer_reviews_extracted`
- `product_details_extracted`
- `ppd_extracted`

### Single Product: One-Shot Manifest Sync (Optional)

If you want an explicit final sync after extraction:

```bash
python chunker/sync_extract_manifest.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5
```

### Batch Mode: Extract + Sync All Products

Run all three extractors for every product directory under `chunks/`, then sync each manifest:

```bash
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/
```

Useful options:

```bash
# smoke run on the first product only
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/ --limit 1

# stop immediately when any extraction/sync fails
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/ --strict
```

---

## Output Format

Each run creates a timestamped folder under `raw_html_output/` (e.g. `20260402T011314Z/`).

### `categories/*.html`
Raw browser-rendered HTML of each Bestsellers listing page. File naming: `category_001_<hash>.html`.

### `products/*.html`
Raw browser-rendered HTML of each product detail page. File naming: `product_0001_<ASIN>.html`.

### `xhr/*.jsonl`
Captured XHR/fetch responses per page (if enabled). Each line is a JSON object with URL, status, headers, and response body.

### `meta/requests.jsonl`
One JSON line per HTTP request (both category and product). Fields include:
- `request_type` — `"category"` or `"product"`
- `source_url`, `requested_url`, `final_url` — URL chain
- `asin` — extracted ASIN (product requests only)
- `fetcher` — which fetcher was used (`dynamic` / `stealth`)
- `status_code`, `reason`, `headers`, `cookies`, `history`
- `blocked` — `true` if the page appears to be a CAPTCHA/anti-bot page
- `html_file`, `html_size` — path and size of saved HTML
- `xhr_file`, `xhr_count` — path and count of captured XHR

### `meta/product_links.jsonl`
All product URLs discovered from category pages. Fields:
- `discovered_order` — discovery sequence number
- `discovered_from` — the category page URL
- `raw_url` — original href from the page
- `canonical_url` — cleaned `https://www.amazon.com/dp/<ASIN>` form
- `asin` — extracted 10-character ASIN

### `meta/crawl_summary.json`
Run-level summary including input config and final stats:
```json
{
  "run_id": "20260402T011314Z",
  "inputs": { "category_url": "...", "max_category_pages": 1, "max_products": 1 },
  "stats": {
    "category_success": 1,
    "category_failed": 0,
    "products_discovered": 32,
    "product_targets": 1,
    "product_success": 1,
    "product_failed": 0
  }
}
```

---

## MCP Server (Claude-Code Integration)

The scraper can be used as an MCP (Model Context Protocol) server, exposing two tools for Claude-Code:

| Tool | Description |
|---|---|
| `crawl_bestseller_list` | Phase 1: Crawl category pages, discover Top 50 product links |
| `crawl_product_details` | Phase 2: Crawl product detail pages (async concurrent) |

### Setup for Claude-Code

Add to `.claude/mcp.json` (project-level) or `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "amazon-scraper": {
      "command": "python",
      "args": ["src/mcp_server.py"],
      "cwd": "<absolute-path-to-project-root>"
    }
  }
}
```

### Phased CLI Usage

The CLI now supports running individual phases:

```bash
# Phase 1 only: crawl category pages
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase list

# Phase 2 only: crawl product details from an existing run
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase detail \
  --run-id 20260402T032433Z \
  --max-concurrency 3

# Both phases (default, backward-compatible)
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase all
```

| New Argument | Default | Description |
|---|---|---|
| `--phase` | `all` | `list` (Phase 1 only), `detail` (Phase 2 only), `all` (both) |
| `--run-id` | `None` | Existing run ID to resume (required for `--phase detail`) |
| `--max-concurrency` | `3` | Max concurrent browser tabs for product detail crawling |

---

## Known Limitations

- **No structured data extraction** — this tool only archives raw HTML. Parsing product titles, prices, ratings, etc. must be done by a separate downstream process.
- **Amazon anti-bot blocking** — product detail pages are frequently blocked by CAPTCHA even with `StealthyFetcher`. The spider detects and flags these (`blocked: true`) but cannot bypass them. Using `--prefer-stealth`, `--solve-cloudflare`, `--proxy`, and larger `--delay-ms` values may help.
- **Single category per run** — each invocation crawls one category URL. To scrape multiple categories, run the script multiple times.
- **No incremental/resume** — each run starts fresh. There is no checkpoint or resume mechanism.
