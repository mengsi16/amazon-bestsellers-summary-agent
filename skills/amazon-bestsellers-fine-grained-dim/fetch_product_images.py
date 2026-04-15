#!/usr/bin/env python3
"""
Generic product image downloader for fine-grained segmentation.

Usage:
    python fetch_product_images.py --download-plan plan.json
    python fetch_product_images.py --output-dir out_dir \
      --product "001_B0XXXXX" "https://..." "https://..." \
      --product "002_B0YYYYY" "https://..."
"""

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _safe_suffix_from_url(url: str) -> str:
    filename = url.split("?")[0].rstrip("/").split("/")[-1]
    if "." in filename:
        suffix = "." + filename.rsplit(".", 1)[-1]
        if 1 <= len(suffix) <= 6:
            return suffix
    return ".jpg"


def _validate_plan(plan: dict) -> None:
    if not plan.get("output_dir"):
        raise ValueError("download plan missing output_dir")
    products = plan.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("download plan missing non-empty products")
    for idx, product in enumerate(products):
        if not product.get("dir_name"):
            raise ValueError(f"products[{idx}] missing dir_name")
        if "urls" not in product:
            raise ValueError(f"products[{idx}] missing urls")


def _build_plan_from_cli(output_dir: str, product_args: list[list[str]]) -> dict:
    if not output_dir:
        raise ValueError("direct mode missing output_dir")
    if not product_args:
        raise ValueError("direct mode requires at least one --product")

    products: list[dict] = []
    for idx, row in enumerate(product_args):
        if len(row) < 2:
            raise ValueError(
                f"--product entry #{idx} must include dir_name and at least one url"
            )
        products.append(
            {
                "dir_name": row[0],
                "urls": row[1:],
            }
        )

    plan = {
        "output_dir": output_dir,
        "products": products,
    }
    _validate_plan(plan)
    return plan


def _load_plan(plan_path: Path) -> dict:
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan not found: {plan_path}")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    _validate_plan(plan)
    return plan


def _download(url: str, dst: Path, timeout: int = 30) -> bool:
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.amazon.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
            data = response.read()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def run_with_plan(plan: dict) -> int:
    output_dir = Path(plan["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    total = 0
    ok = 0

    for product in plan["products"]:
        dir_name = product["dir_name"]
        urls = product.get("urls", [])
        product_dir = output_dir / dir_name
        product_dir.mkdir(parents=True, exist_ok=True)

        image_rows = []
        product_ok = 0

        for idx, url in enumerate(urls, start=1):
            total += 1
            suffix = _safe_suffix_from_url(url)
            filename = f"product_img_{idx:03d}{suffix}"
            save_path = product_dir / filename
            success = _download(url, save_path)
            if success:
                ok += 1
                product_ok += 1
            image_rows.append(
                {
                    "index": idx,
                    "url": url,
                    "filename": filename,
                    "local_path": str(save_path),
                    "status": "OK" if success else "FAILED",
                }
            )
            if idx < len(urls):
                time.sleep(0.2)

        results.append(
            {
                "dir_name": dir_name,
                "image_count": len(urls),
                "success_count": product_ok,
                "status": (
                    "SUCCESS"
                    if product_ok == len(urls)
                    else "PARTIAL"
                    if product_ok > 0
                    else "ALL_FAILED"
                ),
                "images": image_rows,
            }
        )

    manifest = {
        "output_dir": str(output_dir),
        "total_images": total,
        "total_success": ok,
        "products": results,
    }

    manifest_path = output_dir / "download_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Downloaded {ok}/{total} images")
    print(f"Manifest: {manifest_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download product images from a plan JSON or direct URL arguments"
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--download-plan", type=Path, help="Path to plan json")
    input_group.add_argument("--output-dir", type=str, help="Output dir for direct CLI mode")
    parser.add_argument(
        "--product",
        action="append",
        nargs="+",
        metavar="ITEM",
        help="Direct mode: --product <dir_name> <url1> [url2 ...], repeatable",
    )
    args = parser.parse_args()

    if args.download_plan:
        try:
            plan = _load_plan(args.download_plan)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Invalid plan: {exc}", file=sys.stderr)
            raise SystemExit(2)
    else:
        try:
            plan = _build_plan_from_cli(args.output_dir, args.product)
        except ValueError as exc:
            print(f"Invalid CLI input: {exc}", file=sys.stderr)
            raise SystemExit(3)

    raise SystemExit(run_with_plan(plan))


if __name__ == "__main__":
    main()
