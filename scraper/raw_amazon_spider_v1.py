from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from scrapling.engines.toolbelt.custom import Response
from scrapling.fetchers import DynamicFetcher, StealthyFetcher

LOGGER = logging.getLogger("raw_amazon_spider")

HREF_RE = re.compile(r"href=[\"'](?P<href>[^\"']+)[\"']", re.IGNORECASE)
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE)
PRODUCT_HINT_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/", re.IGNORECASE)
ANTI_BOT_MARKERS = (
    "captcha",
    "robot check",
    "type the characters you see in this image",
    "enter the characters you see below",
    "sorry, we just need to make sure you're not a robot",
    "validatecaptcha",
)

SERVICE_ERROR_MARKERS = (
    "503 - service unavailable error",
    "service unavailable error",
    "sorry! something went wrong",
)

PRODUCT_PAGE_MARKERS = (
    "producttitle",
    "product-title",
    "data-asin",
    "add-to-cart",
    "buybox",
)


@dataclass(frozen=True)
class CrawlConfig:
    category_url: str
    output_dir: Path
    max_category_pages: int
    max_products: int | None
    timeout_ms: int
    wait_ms: int
    delay_ms: int
    retries_per_fetcher: int
    headless: bool
    prefer_stealth: bool
    solve_cloudflare: bool
    capture_xhr_pattern: str | None
    useragent: str | None
    proxy: str | None
    scroll_category: bool
    scroll_pause_ms: int


@dataclass(frozen=True)
class FetchResult:
    response: Response | None
    fetcher_name: str
    error: str | None
    blocked: bool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def short_hash(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:16]


def safe_slug(value: str, max_length: int = 96) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    if not normalized:
        normalized = "item"
    return normalized[:max_length]


def is_amazon_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "amazon." in netloc


def canonical_category_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.split("/ref=", 1)[0]
    query = parse_qs(parsed.query)
    query_parts: list[str] = []
    if "pg" in query and query["pg"]:
        query_parts.append(f"pg={query['pg'][0]}")
    clean_query = "&".join(query_parts)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", clean_query, ""))


def extract_asin(url: str) -> str | None:
    match = ASIN_RE.search(url)
    if not match:
        return None
    return match.group(1).upper()


def canonical_product_url(url: str) -> str:
    parsed = urlparse(url)
    asin = extract_asin(url)
    if asin:
        return urlunparse((parsed.scheme or "https", parsed.netloc, f"/dp/{asin}", "", "", ""))
    path = parsed.path.split("/ref=", 1)[0]
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", "", ""))


def iter_hrefs(base_url: str, html_content: str) -> list[str]:
    links: list[str] = []
    for match in HREF_RE.finditer(html_content):
        href = match.group("href").replace("&amp;", "&").strip()
        if not href or href.startswith("#"):
            continue
        if href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        absolute = urljoin(base_url, href)
        links.append(absolute)
    return links


def extract_product_links(base_url: str, html_content: str) -> list[dict[str, str | None]]:
    results: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for absolute in iter_hrefs(base_url, html_content):
        if not is_amazon_url(absolute):
            continue
        if not PRODUCT_HINT_RE.search(urlparse(absolute).path):
            continue

        canonical = canonical_product_url(absolute)
        if canonical in seen:
            continue

        seen.add(canonical)
        results.append(
            {
                "raw_url": absolute,
                "canonical_url": canonical,
                "asin": extract_asin(canonical),
            }
        )
    return results


def extract_category_page_links(
    base_url: str, html_content: str, target_category_path: str
) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for absolute in iter_hrefs(base_url, html_content):
        if not is_amazon_url(absolute):
            continue

        canonical = canonical_category_url(absolute)
        parsed = urlparse(canonical)
        lower_url = canonical.lower()
        lower_path = parsed.path.lower()
        if "/dp/" in lower_path or "/gp/product/" in lower_path:
            continue

        # Keep crawling bounded to the same category path provided by the user.
        if parsed.path != target_category_path:
            continue

        has_bestseller_hint = (
            "bestsellers" in lower_path
            or "zg_bs" in lower_url
            or "pg=" in parsed.query.lower()
        )
        if not has_bestseller_hint:
            continue

        if canonical in seen:
            continue

        seen.add(canonical)
        results.append(canonical)

    return results


def is_probably_block_page(html_content: str) -> bool:
    content = html_content.lower()
    return any(marker in content for marker in ANTI_BOT_MARKERS)


def is_service_error_page(html_content: str) -> bool:
    content = html_content.lower()
    return any(marker in content for marker in SERVICE_ERROR_MARKERS)


def is_valid_product_page(html_content: str) -> bool:
    """Return True if the HTML looks like a real Amazon product detail page."""
    if is_probably_block_page(html_content) or is_service_error_page(html_content):
        return False
    content = html_content.lower()
    return any(marker in content for marker in PRODUCT_PAGE_MARKERS)


class RawAmazonSpider:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        self.run_root = self.config.output_dir / self.run_id
        self.categories_dir = self.run_root / "categories"
        self.products_dir = self.run_root / "products"
        self.meta_dir = self.run_root / "meta"
        self.xhr_dir = self.run_root / "xhr"

        for folder in [self.categories_dir, self.products_dir, self.meta_dir, self.xhr_dir]:
            folder.mkdir(parents=True, exist_ok=True)

        self.requests_log_path = self.meta_dir / "requests.jsonl"
        self.product_links_log_path = self.meta_dir / "product_links.jsonl"
        self.summary_path = self.meta_dir / "crawl_summary.json"

    def crawl(self) -> dict[str, Any]:
        category_queue: list[str] = [canonical_category_url(self.config.category_url)]
        visited_category: set[str] = set()
        seed_category_path = urlparse(category_queue[0]).path

        discovered_products: list[dict[str, Any]] = []
        seen_products: set[str] = set()

        category_success = 0
        category_failed = 0

        while category_queue and len(visited_category) < self.config.max_category_pages:
            category_url = category_queue.pop(0)
            if category_url in visited_category:
                continue

            visited_category.add(category_url)
            page_index = len(visited_category)
            LOGGER.info("[Category %s] %s", page_index, category_url)

            category_page_id = f"category_{page_index:03d}_{short_hash(category_url)}"
            scroll_action = self._make_category_scroll_action() if self.config.scroll_category else None
            fetch_result = self._fetch_with_fallback(category_url, page_action=scroll_action)

            category_record: dict[str, Any] = {
                "request_type": "category",
                "source_url": category_url,
                "requested_url": category_url,
                "fetcher": fetch_result.fetcher_name,
                "attempted_at_utc": utc_now_iso(),
                "error": fetch_result.error,
                "blocked": fetch_result.blocked,
            }

            if fetch_result.response is None:
                category_failed += 1
                self._append_jsonl(self.requests_log_path, category_record)
                continue

            response = fetch_result.response
            html_path = self.categories_dir / f"{category_page_id}.html"
            html_path.write_text(response.html_content, encoding="utf-8", errors="replace")
            xhr_path, xhr_count = self._save_captured_xhr(category_page_id, response)

            product_links = extract_product_links(response.url, response.html_content)
            for item in product_links:
                canonical = item["canonical_url"]
                if canonical in seen_products:
                    continue
                seen_products.add(canonical)
                discovered_products.append(
                    {
                        "discovered_order": len(discovered_products) + 1,
                        "discovered_from": response.url,
                        **item,
                    }
                )

            next_pages = extract_category_page_links(
                response.url,
                response.html_content,
                seed_category_path,
            )
            for next_page in next_pages:
                if next_page in visited_category or next_page in category_queue:
                    continue
                if len(visited_category) + len(category_queue) >= self.config.max_category_pages:
                    break
                category_queue.append(next_page)

            category_record.update(
                {
                    "status_code": getattr(response, "status", None),
                    "reason": getattr(response, "reason", None),
                    "final_url": response.url,
                    "html_file": str(html_path),
                    "html_size": len(response.html_content),
                    "xhr_file": str(xhr_path) if xhr_path else None,
                    "xhr_count": xhr_count,
                    "headers": self._to_plain_dict(getattr(response, "headers", {})),
                    "request_headers": self._to_plain_dict(
                        getattr(response, "request_headers", {})
                    ),
                    "cookies": self._to_json_safe(getattr(response, "cookies", [])),
                    "history": self._serialize_history(getattr(response, "history", [])),
                    "discovered_product_links": len(product_links),
                    "discovered_next_category_pages": len(next_pages),
                }
            )
            self._append_jsonl(self.requests_log_path, category_record)
            category_success += 1

            if self.config.delay_ms > 0:
                time.sleep(self.config.delay_ms / 1000.0)

        for item in discovered_products:
            self._append_jsonl(self.product_links_log_path, item)

        if self.config.max_products is not None:
            product_targets = discovered_products[: self.config.max_products]
        else:
            product_targets = discovered_products

        product_success = 0
        product_failed = 0

        max_product_retries = 2
        backoff_multiplier = 2.0

        if product_targets:
            cooldown = max(self.config.delay_ms / 1000.0 * 3, 15.0)
            LOGGER.info("Cooling down %.1fs before product phase …", cooldown)
            time.sleep(cooldown)

        for index, item in enumerate(product_targets, start=1):
            target_url = str(item["canonical_url"])
            asin = item.get("asin")
            product_id = asin if asin else short_hash(target_url)
            page_id = f"product_{index:04d}_{safe_slug(product_id)}"

            LOGGER.info("[Product %s/%s] %s", index, len(product_targets), target_url)

            valid = False
            last_fetch_result: FetchResult | None = None

            for product_attempt in range(1, max_product_retries + 1):
                fetch_result = self._fetch_with_fallback(target_url, force_stealth=True, google_search=True)
                last_fetch_result = fetch_result

                if fetch_result.response is None:
                    break

                html = fetch_result.response.html_content
                if is_valid_product_page(html):
                    valid = True
                    break

                reason = "503/service-error" if is_service_error_page(html) else "captcha/block"
                LOGGER.warning(
                    "[Product %s] attempt %s/%s got %s page (%s bytes)",
                    product_id, product_attempt, max_product_retries,
                    reason, len(html),
                )

                if product_attempt < max_product_retries:
                    wait = self.config.delay_ms / 1000.0 * backoff_multiplier * product_attempt
                    LOGGER.info("Backing off %.1fs before retry …", wait)
                    time.sleep(wait)

            fetch_result = last_fetch_result  # type: ignore[assignment]
            product_record: dict[str, Any] = {
                "request_type": "product",
                "source_url": str(item.get("discovered_from") or ""),
                "requested_url": target_url,
                "asin": asin,
                "fetcher": fetch_result.fetcher_name,
                "attempted_at_utc": utc_now_iso(),
                "error": fetch_result.error,
                "blocked": fetch_result.blocked,
                "valid_product_page": valid,
            }

            if fetch_result.response is None:
                product_failed += 1
                self._append_jsonl(self.requests_log_path, product_record)
                continue

            response = fetch_result.response

            if not valid:
                product_record["blocked"] = True
                product_record["error"] = (
                    product_record.get("error") or
                    "page did not contain product markers after retries"
                )

            html_path = self.products_dir / f"{page_id}.html"
            html_path.write_text(response.html_content, encoding="utf-8", errors="replace")
            xhr_path, xhr_count = self._save_captured_xhr(page_id, response)

            product_record.update(
                {
                    "status_code": getattr(response, "status", None),
                    "reason": getattr(response, "reason", None),
                    "final_url": response.url,
                    "html_file": str(html_path),
                    "html_size": len(response.html_content),
                    "xhr_file": str(xhr_path) if xhr_path else None,
                    "xhr_count": xhr_count,
                    "headers": self._to_plain_dict(getattr(response, "headers", {})),
                    "request_headers": self._to_plain_dict(
                        getattr(response, "request_headers", {})
                    ),
                    "cookies": self._to_json_safe(getattr(response, "cookies", [])),
                    "history": self._serialize_history(getattr(response, "history", [])),
                }
            )
            self._append_jsonl(self.requests_log_path, product_record)

            if valid:
                product_success += 1
            else:
                product_failed += 1
                LOGGER.warning("[Product %s] saved but marked as INVALID", product_id)

            if self.config.delay_ms > 0:
                time.sleep(self.config.delay_ms / 1000.0)

        summary = {
            "run_id": self.run_id,
            "started_at_utc": utc_now_iso(),
            "inputs": {
                "category_url": self.config.category_url,
                "max_category_pages": self.config.max_category_pages,
                "max_products": self.config.max_products,
            },
            "outputs": {
                "run_root": str(self.run_root),
                "categories_dir": str(self.categories_dir),
                "products_dir": str(self.products_dir),
                "meta_dir": str(self.meta_dir),
                "xhr_dir": str(self.xhr_dir),
                "requests_jsonl": str(self.requests_log_path),
                "product_links_jsonl": str(self.product_links_log_path),
            },
            "stats": {
                "category_success": category_success,
                "category_failed": category_failed,
                "products_discovered": len(discovered_products),
                "product_targets": len(product_targets),
                "product_success": product_success,
                "product_failed": product_failed,
            },
        }

        self.summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    def _fetch_with_fallback(self, url: str, page_action: Any = None, force_stealth: bool = False, google_search: bool = False) -> FetchResult:
        ordered_fetchers: list[tuple[str, type[Any]]]
        if force_stealth:
            ordered_fetchers = [("stealth", StealthyFetcher)]
        elif self.config.prefer_stealth:
            ordered_fetchers = [("stealth", StealthyFetcher), ("dynamic", DynamicFetcher)]
        else:
            ordered_fetchers = [("dynamic", DynamicFetcher), ("stealth", StealthyFetcher)]

        last_error: str | None = None

        for fetcher_name, fetcher_cls in ordered_fetchers:
            for attempt in range(1, self.config.retries_per_fetcher + 1):
                try:
                    response = fetcher_cls.fetch(url, **self._build_fetch_kwargs(fetcher_name, page_action=page_action, google_search=google_search))
                    blocked = is_probably_block_page(response.html_content)

                    should_fallback = (
                        blocked
                        and fetcher_name == "dynamic"
                        and any(name == "stealth" for name, _ in ordered_fetchers)
                    )
                    if should_fallback:
                        last_error = "dynamic fetch likely hit anti-bot page; switching fetcher"
                        LOGGER.warning("%s | %s", url, last_error)
                        break

                    return FetchResult(
                        response=response,
                        fetcher_name=fetcher_name,
                        error=None,
                        blocked=blocked,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"
                    LOGGER.warning(
                        "Fetch failed (%s attempt %s/%s): %s",
                        fetcher_name,
                        attempt,
                        self.config.retries_per_fetcher,
                        last_error,
                    )
                    time.sleep(0.5 + random.random() * 0.5)

        return FetchResult(response=None, fetcher_name="none", error=last_error, blocked=False)

    def _build_fetch_kwargs(self, fetcher_name: str, page_action: Any = None, google_search: bool = False) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "headless": self.config.headless,
            "timeout": self.config.timeout_ms,
            "wait": self.config.wait_ms,
            "network_idle": True,
            "load_dom": True,
            "disable_resources": False,
            "google_search": google_search,
            "retries": 1,
            "retry_delay": 1,
        }

        if self.config.useragent:
            kwargs["useragent"] = self.config.useragent

        if self.config.proxy:
            kwargs["proxy"] = self.config.proxy

        if self.config.capture_xhr_pattern:
            kwargs["capture_xhr"] = self.config.capture_xhr_pattern

        if fetcher_name == "stealth" and self.config.solve_cloudflare:
            kwargs["solve_cloudflare"] = True

        if page_action is not None:
            kwargs["page_action"] = page_action

        return kwargs

    def _make_category_scroll_action(self):
        """Return a page_action callable that scrolls the Bestsellers page to
        trigger lazy-loaded XHR and render all product items (up to Top 50)."""
        pause_ms = self.config.scroll_pause_ms

        def _scroll(page) -> None:
            max_scrolls = 30
            prev_count = 0
            stale_rounds = 0

            for i in range(1, max_scrolls + 1):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(pause_ms)

                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

                count = page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[href*="/dp/"]');
                        const asins = new Set();
                        for (const a of links) {
                            const m = a.href.match(/\\/dp\\/([A-Z0-9]{10})/i);
                            if (m) asins.add(m[1].toUpperCase());
                        }
                        return asins.size;
                    }
                """)

                LOGGER.debug("Scroll %s/%s – %s unique ASINs found", i, max_scrolls, count)

                if count >= 50:
                    LOGGER.info("Scroll complete: %s ASINs found (>= 50)", count)
                    break

                if count <= prev_count:
                    stale_rounds += 1
                    if stale_rounds >= 4:
                        LOGGER.info(
                            "No new ASINs after %s consecutive scrolls, stopping at %s",
                            stale_rounds, count,
                        )
                        break
                else:
                    stale_rounds = 0

                prev_count = count

            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)

        return _scroll

    def _save_captured_xhr(self, page_id: str, response: Response) -> tuple[Path | None, int]:
        captured = list(getattr(response, "captured_xhr", []) or [])
        if not captured:
            return None, 0

        output_path = self.xhr_dir / f"{page_id}.jsonl"
        with output_path.open("w", encoding="utf-8") as file_obj:
            for xhr_response in captured:
                record = {
                    "url": getattr(xhr_response, "url", None),
                    "status": getattr(xhr_response, "status", None),
                    "reason": getattr(xhr_response, "reason", None),
                    "encoding": getattr(xhr_response, "encoding", None),
                    "headers": self._to_plain_dict(getattr(xhr_response, "headers", {})),
                    "request_headers": self._to_plain_dict(
                        getattr(xhr_response, "request_headers", {})
                    ),
                    "cookies": self._to_json_safe(getattr(xhr_response, "cookies", [])),
                    "body": getattr(xhr_response, "text", ""),
                }
                file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")

        return output_path, len(captured)

    @staticmethod
    def _serialize_history(history: list[Response]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in history:
            result.append(
                {
                    "url": getattr(item, "url", None),
                    "status": getattr(item, "status", None),
                    "reason": getattr(item, "reason", None),
                }
            )
        return result

    @staticmethod
    def _to_plain_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return {str(key): val for key, val in value.items()}
        return {}

    @staticmethod
    def _to_json_safe(value: Any) -> Any:
        try:
            json.dumps(value)
            return value
        except TypeError:
            if isinstance(value, (list, tuple, set)):
                return [RawAmazonSpider._to_json_safe(item) for item in value]
            if isinstance(value, dict):
                return {
                    str(key): RawAmazonSpider._to_json_safe(item)
                    for key, item in value.items()
                }
            return str(value)

    @staticmethod
    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Raw Amazon crawler: crawl a Bestsellers category URL, then crawl product detail pages, "
            "and persist rendered HTML + raw metadata for later processing."
        )
    )

    parser.add_argument("--category-url", required=True, help="Amazon Bestsellers category URL")
    parser.add_argument(
        "--output-dir",
        default="raw_html_output",
        help="Directory where raw crawl artifacts are stored",
    )
    parser.add_argument(
        "--max-category-pages",
        type=int,
        default=5,
        help="Maximum Bestsellers category pages to crawl",
    )
    parser.add_argument(
        "--max-products",
        type=int,
        default=None,
        help="Maximum product detail pages to crawl",
    )
    parser.add_argument("--timeout-ms", type=int, default=90000, help="Fetcher timeout in ms")
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=2500,
        help="Extra wait after page settles, in ms",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=3500,
        help="Delay between requests in ms",
    )
    parser.add_argument(
        "--retries-per-fetcher",
        type=int,
        default=2,
        help="Retry attempts per fetcher before fallback",
    )

    headless_group = parser.add_mutually_exclusive_group()
    headless_group.add_argument("--headless", dest="headless", action="store_true")
    headless_group.add_argument("--headful", dest="headless", action="store_false")
    parser.set_defaults(headless=True)

    stealth_group = parser.add_mutually_exclusive_group()
    stealth_group.add_argument(
        "--prefer-stealth",
        dest="prefer_stealth",
        action="store_true",
        default=True,
        help="Try StealthyFetcher first (default)",
    )
    stealth_group.add_argument(
        "--no-prefer-stealth",
        dest="prefer_stealth",
        action="store_false",
        help="Try DynamicFetcher first instead of StealthyFetcher",
    )
    parser.add_argument(
        "--solve-cloudflare",
        action="store_true",
        help="Enable Cloudflare challenge handling when stealth fetcher is used",
    )

    capture_group = parser.add_mutually_exclusive_group()
    capture_group.add_argument(
        "--capture-xhr-pattern",
        default=".*",
        help="Regex pattern for XHR/fetch capture; default captures all",
    )
    capture_group.add_argument(
        "--no-capture-xhr",
        action="store_true",
        help="Disable XHR/fetch capture",
    )

    parser.add_argument("--useragent", default=None, help="Optional custom User-Agent")
    parser.add_argument("--proxy", default=None, help="Optional proxy string")

    parser.add_argument(
        "--no-scroll",
        action="store_true",
        help="Disable auto-scrolling on category pages (scrolling triggers lazy-loaded products)",
    )
    parser.add_argument(
        "--scroll-pause-ms",
        type=int,
        default=1500,
        help="Pause between scroll steps in ms (default: 1500)",
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> CrawlConfig:
    if args.max_category_pages < 1:
        raise ValueError("--max-category-pages must be >= 1")
    if args.max_products is not None and args.max_products < 1:
        raise ValueError("--max-products must be >= 1")
    if args.timeout_ms < 1:
        raise ValueError("--timeout-ms must be >= 1")
    if args.wait_ms < 0:
        raise ValueError("--wait-ms must be >= 0")
    if args.delay_ms < 0:
        raise ValueError("--delay-ms must be >= 0")
    if args.retries_per_fetcher < 1:
        raise ValueError("--retries-per-fetcher must be >= 1")

    capture_xhr_pattern = None if args.no_capture_xhr else args.capture_xhr_pattern

    return CrawlConfig(
        category_url=args.category_url,
        output_dir=Path(args.output_dir).resolve(),
        max_category_pages=args.max_category_pages,
        max_products=args.max_products,
        timeout_ms=args.timeout_ms,
        wait_ms=args.wait_ms,
        delay_ms=args.delay_ms,
        retries_per_fetcher=args.retries_per_fetcher,
        headless=args.headless,
        prefer_stealth=args.prefer_stealth,
        solve_cloudflare=args.solve_cloudflare,
        capture_xhr_pattern=capture_xhr_pattern,
        useragent=args.useragent,
        proxy=args.proxy,
        scroll_category=not args.no_scroll,
        scroll_pause_ms=args.scroll_pause_ms,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    try:
        config = build_config(args)
    except ValueError as exc:
        LOGGER.error("Invalid arguments: %s", exc)
        return 2

    spider = RawAmazonSpider(config)
    summary = spider.crawl()

    LOGGER.info("Run finished: %s", spider.run_id)
    LOGGER.info("Output root: %s", spider.run_root)
    LOGGER.info("Summary: %s", spider.summary_path)
    LOGGER.info("Stats: %s", json.dumps(summary["stats"], ensure_ascii=False))

    if summary["stats"]["category_success"] == 0:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
