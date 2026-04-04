#!/usr/bin/env python3
"""
A+ Image Fetcher — 从 batch-run 产出目录下载 Top N 产品的 A+ 图片。

Usage:
    python fetch_aplus_images.py --chunks-dir <out_dir> [--top-n 5] [--output-dir <path>]

功能：
1. 读取 global_manifest.json（或按 {rank}_{ASIN} 目录名排序）定位 Top N 产品
2. 从每个产品的 aplus/extract/aplus_extracted.md 解析 Image Assets 表格，提取图片 URL
3. 如 extracted md 无结果，从 aplus/raw/aplus.html 备用提取
4. 下载图片到 <output-dir>/<rank>_<ASIN>/ 目录
5. 生成 download_manifest.json 记录下载结果

目录结构约定（batch-run 产出）：
    out_dir/{rank}_{ASIN}/aplus/raw/aplus.html
    out_dir/{rank}_{ASIN}/aplus/extract/aplus_extracted.md
    out_dir/global_manifest.json
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


def parse_aplus_image_urls(aplus_md_path: Path) -> list[str]:
    """从 aplus_extracted.md 中解析 Image Assets 表格，提取图片 URL。"""
    if not aplus_md_path.exists():
        return []

    text = aplus_md_path.read_text(encoding="utf-8")
    urls: list[str] = []

    in_image_section = False
    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("## Image Assets"):
            in_image_section = True
            continue

        if in_image_section and stripped.startswith("## "):
            break

        if in_image_section and stripped.startswith("|"):
            # 跳过表头和分隔行
            if "---" in stripped or "Alt" in stripped and "Src" in stripped:
                continue
            # 提取 URL（表格第二列）
            cols = [c.strip() for c in stripped.split("|")]
            for col in cols:
                if col.startswith("http"):
                    urls.append(col)

    return urls


def parse_aplus_html_image_urls(aplus_html_path: Path) -> list[str]:
    """从 aplus.html 中用正则提取所有 A+ 图片 URL（备用方案）。"""
    if not aplus_html_path.exists():
        return []

    html = aplus_html_path.read_text(encoding="utf-8")
    urls: list[str] = []

    # 匹配 data-src 和 src 中的 media-amazon 图片 URL
    patterns = [
        r'data-src="(https://m\.media-amazon\.com/images/S/aplus-media[^"]+)"',
        r'src="(https://m\.media-amazon\.com/images/S/aplus-media[^"]+)"',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html):
            url = match.group(1)
            if url not in urls:
                urls.append(url)

    return urls


def download_image(url: str, save_path: Path, timeout: int = 30) -> bool:
    """下载单张图片，返回是否成功。"""
    try:
        # 创建不验证 SSL 的上下文（某些环境下 Amazon CDN 证书可能有问题）
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


def parse_rank_asin(dir_name: str) -> tuple[str, str]:
    """从目录名 '{rank}_{ASIN}' 中提取 rank 和 ASIN。

    例如 '001_B0XXXXX' -> ('001', 'B0XXXXX')
    """
    parts = dir_name.split("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", dir_name


def get_product_dirs(chunks_dir: Path, top_n: int) -> list[Path]:
    """获取 batch-run 产出目录下前 N 个产品子目录。

    优先读取 global_manifest.json（排名已排序），
    Fallback 按 {rank}_{ASIN} 目录名字典序排序。
    """
    # 优先读取 global_manifest.json
    manifest_path = chunks_dir / "global_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if "products" in manifest:
                dirs = []
                for p in manifest["products"][:top_n]:
                    dir_name = p.get("dir", "")
                    if not dir_name:
                        # 兼容：从 rank + asin 拼接
                        rank = p.get("rank", "")
                        asin = p.get("asin", "")
                        dir_name = f"{rank}_{asin}" if rank and asin else ""
                    if dir_name:
                        d = chunks_dir / dir_name
                        if d.is_dir():
                            dirs.append(d)
                if dirs:
                    return dirs
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback：按目录名排序（{rank}_{ASIN} 格式自然按 rank 升序）
    all_dirs = sorted(
        [d for d in chunks_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
    )
    return all_dirs[:top_n]


def url_to_filename(url: str, index: int) -> str:
    """从 URL 生成文件名。"""
    # 提取文件扩展名
    path_part = url.split("?")[0]
    if "." in path_part.split("/")[-1]:
        ext = "." + path_part.split("/")[-1].rsplit(".", 1)[-1]
        # 清理 Amazon 的尺寸后缀，如 ._SR970,300_.jpg
        ext = re.sub(r"\._[A-Z]+[\d,]+_", "", ext)
        if not ext or ext == ".":
            ext = ".jpg"
    else:
        ext = ".jpg"

    return f"aplus_img_{index:03d}{ext}"


def main():
    parser = argparse.ArgumentParser(
        description="Download A+ images for Top N products from Chunks directory"
    )
    parser.add_argument(
        "--chunks-dir",
        type=Path,
        required=True,
        help="Path to the Chunks directory (e.g., Amazon-Bestsellers-Scraper/Chunks)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="Number of top products to download images for (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for downloaded images (default: <chunks-dir>/../aplus_images)",
    )
    args = parser.parse_args()

    chunks_dir = args.chunks_dir.resolve()
    if not chunks_dir.is_dir():
        print(f"Error: Chunks directory not found: {chunks_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir or (chunks_dir.parent / "aplus_images")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    product_dirs = get_product_dirs(chunks_dir, args.top_n)
    if not product_dirs:
        print("Error: No product directories found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(product_dirs)} product(s) to process:")
    for d in product_dirs:
        print(f"  - {d.name}")

    manifest_results: list[dict] = []

    for idx, prod_dir in enumerate(product_dirs, start=1):
        rank_str, asin = parse_rank_asin(prod_dir.name)
        display_name = prod_dir.name  # e.g. '001_B0XXXXX'
        print(f"\n[{idx}/{len(product_dirs)}] Processing {display_name}...")

        # 新目录结构：{rank}_{ASIN}/aplus/extract/ 和 {rank}_{ASIN}/aplus/raw/
        aplus_md = prod_dir / "aplus" / "extract" / "aplus_extracted.md"
        aplus_html = prod_dir / "aplus" / "raw" / "aplus.html"

        urls = parse_aplus_image_urls(aplus_md)
        if not urls:
            urls = parse_aplus_html_image_urls(aplus_html)

        if not urls:
            print(f"  No A+ images found for {display_name}")
            manifest_results.append({
                "rank": rank_str or str(idx),
                "asin": asin,
                "dir": display_name,
                "status": "NO_IMAGES",
                "image_count": 0,
                "images": [],
            })
            continue

        print(f"  Found {len(urls)} image URL(s)")

        product_output = output_dir / display_name
        product_output.mkdir(parents=True, exist_ok=True)

        images_info: list[dict] = []
        success_count = 0

        for img_idx, url in enumerate(urls, start=1):
            filename = url_to_filename(url, img_idx)
            save_path = product_output / filename
            print(f"  Downloading [{img_idx}/{len(urls)}]: {filename}...")

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

            # 礼貌间隔，避免被封
            time.sleep(0.3)

        manifest_results.append({
            "rank": rank_str or str(idx),
            "asin": asin,
            "dir": display_name,
            "status": "SUCCESS" if success_count > 0 else "ALL_FAILED",
            "image_count": len(urls),
            "success_count": success_count,
            "images": images_info,
        })

    # 写入下载清单
    manifest_path = output_dir / "download_manifest.json"
    manifest_data = {
        "top_n": args.top_n,
        "chunks_dir": str(chunks_dir),
        "output_dir": str(output_dir),
        "products": manifest_results,
    }
    manifest_path.write_text(
        json.dumps(manifest_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 汇总
    total_images = sum(r["image_count"] for r in manifest_results)
    total_success = sum(r.get("success_count", 0) for r in manifest_results)
    print(f"\n{'='*50}")
    print(f"Done! {total_success}/{total_images} images downloaded.")
    print(f"Output: {output_dir}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
