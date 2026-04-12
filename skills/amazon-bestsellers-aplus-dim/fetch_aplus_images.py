#!/usr/bin/env python3
"""
A+ Image Fetcher — 纯下载工具，接收模型构造的下载计划（JSON），执行图片下载。

Usage:
    python fetch_aplus_images.py --download-plan plan.json

设计原则（单一职责）：
  - 路径解析（读 global_manifest.json、定位产品目录）→ 模型负责
  - URL 提取（从 aplus_extracted.md / aplus.html 中提取图片 URL）→ 模型负责
  - 图片下载（给定 URL 列表 + 输出目录，下载到本地）→ 本工具负责

plan.json 格式：
{
    "output_dir": "/absolute/path/to/aplus_images",
    "products": [
        {
            "dir_name": "001_B0XXXXX",
            "urls": [
                "https://m.media-amazon.com/images/S/aplus-media/...",
                "https://m.media-amazon.com/images/S/aplus-media/..."
            ]
        }
    ]
}

产出：
  - 图片文件：{output_dir}/{dir_name}/aplus_img_001.jpg ...
  - 下载清单：{output_dir}/download_manifest.json
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
import ssl
from pathlib import Path


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def url_to_filename(url: str, index: int) -> str:
    """从 URL 生成文件名。"""
    path_part = url.split("?")[0]
    if "." in path_part.split("/")[-1]:
        ext = "." + path_part.split("/")[-1].rsplit(".", 1)[-1]
        ext = re.sub(r"\._[A-Z]+[\d,]+_", "", ext)
        if not ext or ext == ".":
            ext = ".jpg"
    else:
        ext = ".jpg"
    return f"aplus_img_{index:03d}{ext}"


# ---------------------------------------------------------------------------
# I/O: single image download
# ---------------------------------------------------------------------------

def download_image(url: str, save_path: Path, timeout: int = 30) -> bool:
    """下载单张图片，返回是否成功。"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://www.amazon.com/",
        })

        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(data)
            return True

    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        print(f"  [FAIL] {url} -> {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Plan loading & validation (fail-fast)
# ---------------------------------------------------------------------------

def load_download_plan(plan_path: Path) -> dict:
    """读取并校验下载计划 JSON，校验失败立即抛异常（fail-fast）。"""
    if not plan_path.exists():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    if "output_dir" not in plan or not plan["output_dir"]:
        raise ValueError("Plan JSON missing required field: 'output_dir'")
    if "products" not in plan or not plan["products"]:
        raise ValueError("Plan JSON missing or empty required field: 'products'")

    for i, prod in enumerate(plan["products"]):
        if "dir_name" not in prod or not prod["dir_name"]:
            raise ValueError(
                f"Product #{i} missing required field: 'dir_name'"
            )
        if "urls" not in prod:
            raise ValueError(
                f"Product #{i} (dir_name={prod.get('dir_name','?')}) missing required field: 'urls'"
            )

    return plan


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------

def execute_download_plan(plan: dict) -> dict:
    """执行下载计划，返回并持久化 download_manifest。

    Args:
        plan: 已校验的下载计划 dict（来自 load_download_plan）。

    Returns:
        download_manifest dict（同时写入 {output_dir}/download_manifest.json）。
    """
    output_dir = Path(plan["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    products_results: list[dict] = []

    for prod in plan["products"]:
        dir_name = prod["dir_name"]
        urls = prod["urls"]

        if not urls:
            products_results.append({
                "dir_name": dir_name,
                "status": "NO_IMAGES",
                "image_count": 0,
                "success_count": 0,
                "images": [],
            })
            continue

        print(f"  [{dir_name}] Downloading {len(urls)} image(s)...")

        product_output = output_dir / dir_name
        product_output.mkdir(parents=True, exist_ok=True)

        images_info: list[dict] = []
        success_count = 0

        for img_idx, url in enumerate(urls, start=1):
            filename = url_to_filename(url, img_idx)
            save_path = product_output / filename
            print(f"    [{img_idx}/{len(urls)}] {filename}")

            ok = download_image(url, save_path)
            images_info.append({
                "index": img_idx,
                "url": url,
                "filename": filename,
                "local_path": str(save_path),
                "status": "OK" if ok else "FAILED",
            })
            if ok:
                success_count += 1

            if img_idx < len(urls):
                time.sleep(0.3)

        if success_count == len(urls):
            status = "SUCCESS"
        elif success_count > 0:
            status = "PARTIAL"
        else:
            status = "ALL_FAILED"

        products_results.append({
            "dir_name": dir_name,
            "status": status,
            "image_count": len(urls),
            "success_count": success_count,
            "images": images_info,
        })

    manifest = build_download_manifest(
        output_dir=str(output_dir),
        products_results=products_results,
    )

    manifest_path = output_dir / "download_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    total = manifest["total_images"]
    ok = manifest["total_success"]
    print(f"\n{'='*50}")
    print(f"Done! {ok}/{total} images downloaded.")
    print(f"Output: {output_dir}")
    print(f"Manifest: {manifest_path}")

    return manifest


def build_download_manifest(
    output_dir: str,
    products_results: list[dict],
) -> dict:
    """构造 download_manifest 结构体。"""
    return {
        "output_dir": output_dir,
        "total_images": sum(r["image_count"] for r in products_results),
        "total_success": sum(r.get("success_count", 0) for r in products_results),
        "products": products_results,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "A+ Image Fetcher — 纯下载工具。"
            "接收模型构造的下载计划（JSON），执行图片下载。"
        )
    )
    parser.add_argument(
        "--download-plan",
        type=Path,
        required=True,
        help="Path to the download plan JSON file (created by the model)",
    )
    args = parser.parse_args()

    try:
        plan = load_download_plan(args.download_plan)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: Invalid plan file — {e}", file=sys.stderr)
        sys.exit(2)

    execute_download_plan(plan)


if __name__ == "__main__":
    main()
