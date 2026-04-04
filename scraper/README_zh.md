# Amazon 畅销榜原始 HTML 爬虫

## 概述

这是一个 Python 命令行爬虫工具，用于归档 Amazon 畅销榜分类页面及其产品详情页的**原始 HTML**。它不会解析或提取结构化数据 —— 其唯一目的是可靠地下载并持久化完整的浏览器渲染 HTML（加上请求元数据），以便下游工具可以离线处理这些页面。

## 工作原理（两阶段爬取）

1. **第一阶段 —— 分类列表页面**
   - 获取给定的 Amazon 畅销榜分类 URL（例如 `https://www.amazon.com/gp/bestsellers/home-garden/3744541`）
   - **自动滚动页面**触发懒加载 XHR，获取所有产品（Top 50）
   - 从页面中提取所有产品链接（基于 ASIN 的 `/dp/` URL）
   - 跟踪同一分类内的分页链接（由 `--max-category-pages` 控制）

2. **第二阶段 —— 产品详情页面**
   - 从第一阶段发现的产品 URL
   - 逐个爬取每个产品的详情页（由 `--max-products` 控制）
   - 保存每个产品页面的完整渲染 HTML

所有获取的页面都保存为**原始 `.html` 文件**。请求/响应元数据（headers、cookies、状态码、重定向历史等）和发现的产品链接以 **JSONL** 格式记录，便于追溯。

## 主要特性

| 特性 | 描述 |
|---|---|
| **原始 HTML 归档** | 保存每个页面的完整浏览器渲染 HTML —— 爬取时不进行有损解析 |
| **两阶段爬取** | 首先从畅销榜列表页面收集产品 URL，然后爬取每个产品详情页 |
| **自动滚动触发懒加载** | 自动滚动分类页面触发 Amazon 的懒加载 XHR，确保发现所有 Top 50 产品（而不是仅初始的 ~30 个） |
| **双抓取器自动回退** | 使用 scrapling 库的 `DynamicFetcher` 和 `StealthyFetcher`；主抓取器被拦截时自动回退 |
| **反爬虫检测** | 检测 CAPTCHA / 机器人检查页面并在元数据中标记为 `blocked` |
| **XHR 捕获** | 可选地捕获页面加载期间发出的所有 XHR/fetch 网络请求（包括懒加载响应） |
| **分类分页** | 跟踪同一畅销榜分类路径内的 `?pg=` 分页 |
| **结构化元数据** | 将每个请求记录到 `requests.jsonl`，包含状态、headers、cookies、重定向历史和时序信息 |
| **代理支持** | 所有请求可选代理 (`--proxy`) |
| **请求节流** | 可配置的请求间隔 (`--delay-ms`) 以降低检测风险 |
| **无头/有头模式** | 以无头模式（默认）或有头模式 (`--headful`) 运行浏览器以进行调试 |
| **命令行驱动** | 所有选项通过命令行参数传递；无需配置文件 |

---

## 项目结构

```
Amazon-Bestsellers-Scraper/
├── src/
│   ├── raw_amazon_spider.py   # 主爬虫脚本（入口点）
│   ├── mcp_server.py          # MCP Server（Claude-Code 集成）
│   ├── requirements.txt       # Python 依赖
│   └── Makefile               # 快捷命令（setup, fmt）
├── raw_html_output/           # 爬取输出根目录（git-ignored）
│   └── <run_id>/              # 每次运行一个文件夹，例如 20260402T011314Z
│       ├── categories/        # 畅销榜列表页面的原始 HTML
│       ├── products/          # 产品详情页的原始 HTML
│       ├── xhr/               # 捕获的 XHR 响应（JSONL）
│       └── meta/
│           ├── requests.jsonl       # 完整请求/响应日志
│           ├── product_links.jsonl  # 所有发现的产品 URL + ASIN
│           └── crawl_summary.json   # 运行配置、统计、输出路径
└── README.md / README_zh.md
```

---

## 安装

```bash
# 1. 创建并激活虚拟环境
python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# 2. 安装依赖
pip install -r src/requirements.txt

# 3. 安装 Chromium 浏览器（scrapling 所需）
python -m playwright install chromium
```

### 依赖

| 包 | 用途 |
|---|---|
| `scrapling[fetchers]==0.4.3` | 基于浏览器的抓取（DynamicFetcher / StealthyFetcher） |
| `playwright==1.47.0` | 无头 Chromium 自动化（scrapling 使用） |
| `python-dotenv==1.0.1` | 环境变量加载 |

---

## 用法

推荐使用统一入口 `main.py`（位于项目根目录），它会串联完整流程：

1. scraper（抓取）
2. chunker（分块）
3. extract + manifest（提取并生成全局清单）

### 统一入口（推荐）

```bash
# 在项目根目录执行
python main.py "https://www.amazon.com/gp/bestsellers/home-garden/3744541/ref=pd_zg_hrsr_home-garden"
```

常用参数：

```bash
# 指定 run_id（便于复跑/追踪）
python main.py "<category_url>" --run-id 20260402T035937Z

# 仅重建分块/提取/manifest（跳过网络爬取）
python main.py "<category_url>" --run-id 20260402T035937Z --skip-scrape

# 只重建 organized 目录与全局 manifest（跳过抓取和分块）
python main.py "<category_url>" --run-id 20260402T035937Z --skip-scrape --skip-chunk

# 限制抓取规模
python main.py "<category_url>" --max-category-pages 1 --max-products 50
```

### 低层入口（高级）

如需单独调试爬虫阶段，仍可直接使用 `raw_amazon_spider.py`。所有选项通过 CLI 参数传递。

### 基本示例

```bash
# 爬取 "真空压缩袋" 畅销榜分类
# 获取最多 2 个分类页面，然后爬取最多 50 个产品详情页
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --max-category-pages 2 \
  --max-products 50
```

### 快速测试运行

```bash
# 快速测试：1 个分类页面，1 个产品页面
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --max-category-pages 1 \
  --max-products 1
```

### 控制滚动行为

```bash
# 禁用自动滚动（如果你只需要首屏的 ~30 个产品）
python raw_amazon_spider.py \
  --category-url "..." \
  --no-scroll

# 加快滚动速度（减少暂停时间）
python raw_amazon_spider.py \
  --category-url "..." \
  --scroll-pause-ms 800
```

### 完整选项

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
                            [--no-scroll]
                            [--scroll-pause-ms MS]
                            [--log-level {DEBUG,INFO,WARNING,ERROR}]
```

| 参数 | 默认值 | 描述 |
|---|---|---|
| `--category-url` | *(必需)* | 要爬取的 Amazon 畅销榜分类 URL |
| `--output-dir` | `raw_html_output` | 爬取输出的根目录 |
| `--max-category-pages` | `1` | 要爬取的最大畅销榜列表页面数（分页） |
| `--max-products` | `None`（全部） | 要爬取的最大产品详情页数。`None` = 爬取所有发现的 |
| `--timeout-ms` | `90000` | 浏览器页面加载超时（毫秒） |
| `--wait-ms` | `2500` | 页面稳定后的额外等待时间（毫秒） |
| `--delay-ms` | `1200` | 连续请求之间的延迟（毫秒） |
| `--retries-per-fetcher` | `2` | 每个抓取器回退前的重试次数 |
| `--headless` / `--headful` | `--headless` | 以无头模式或有 UI 的可见模式运行浏览器 |
| `--prefer-stealth` | `false` | 优先尝试 `StealthyFetcher` |
| `--solve-cloudflare` | `false` | 启用 Cloudflare 挑战解决（仅 stealth 抓取器） |
| `--capture-xhr-pattern` | `.*`（全部） | 过滤捕获的 XHR 请求的正则表达式 |
| `--no-capture-xhr` | — | 完全禁用 XHR 捕获 |
| `--useragent` | `None` | 自定义 User-Agent 字符串 |
| `--proxy` | `None` | 代理 URL（例如 `http://user:pass@host:port`） |
| `--no-scroll` | *(关闭)* | 禁用分类页面的自动滚动 |
| `--scroll-pause-ms` | `1500` | 每次滚动步骤后的暂停时间（毫秒） |
| `--log-level` | `INFO` | 日志详细程度 |

---

## 分块提取与 Manifest 同步

当 `static_chunker.py` 生成分块文件和 `manifest.json` 后，可以执行三段提取脚本生成 markdown 结果。

### 单商品：执行三段提取

```bash
python chunker/customer_reviews_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/customer_reviews.html
python chunker/product_details_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/product_details.html
python chunker/ppd_extract.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5/ppd.html
```

这三个提取脚本会自动回写 `manifest.json` 的 `blocks` 字段：
- `customer_reviews_extracted`
- `product_details_extracted`
- `ppd_extracted`

### 单商品：一键同步 Manifest（可选）

如果你希望在提取后再显式同步一次：

```bash
python chunker/sync_extract_manifest.py chunks/20260402T035937Z/product_0001_B0DRNRC5H5/B0DRNRC5H5
```

### 批量模式：全量提取并同步

对 `chunks/` 下所有商品目录执行三段提取，并同步每个商品的 manifest：

```bash
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/
```

常用选项：

```bash
# 冒烟运行：只处理第一个商品
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/ --limit 1

# 严格模式：任一步失败立即停止
python chunker/batch_extract_and_sync.py chunks/20260402T035937Z/ --strict
```

---

## 输出格式

每次运行会在 `raw_html_output/` 下创建一个带时间戳的文件夹（例如 `20260402T011314Z/`）。

### `categories/*.html`
每个畅销榜列表页面的原始浏览器渲染 HTML。文件命名：`category_001_<hash>.html`

### `products/*.html`
每个产品详情页的原始浏览器渲染 HTML。文件命名：`product_0001_<ASIN>.html`

### `xhr/*.jsonl`
每个页面捕获的 XHR/fetch 响应（如果启用）。每行是一个 JSON 对象，包含 URL、状态、headers 和响应体。

### `meta/requests.jsonl`
每个 HTTP 请求一行（分类和产品）。字段包括：
- `request_type` — `"category"` 或 `"product"`
- `source_url`, `requested_url`, `final_url` — URL 链
- `asin` — 提取的 ASIN（仅产品请求）
- `fetcher` — 使用的抓取器（`dynamic` / `stealth`）
- `status_code`, `reason`, `headers`, `cookies`, `history`
- `blocked` — 如果页面是 CAPTCHA/反机器人页面则为 `true`
- `html_file`, `html_size` — 保存的 HTML 路径和大小
- `xhr_file`, `xhr_count` — 捕获的 XHR 路径和数量

### `meta/product_links.jsonl`
从分类页面发现的所有产品 URL。字段：
- `discovered_order` — 发现序列号
- `discovered_from` — 来源分类页面 URL
- `raw_url` — 页面中的原始 href
- `canonical_url` — 清理后的 `https://www.amazon.com/dp/<ASIN>` 格式
- `asin` — 提取的 10 字符 ASIN

### `meta/crawl_summary.json`
运行级摘要，包括输入配置和最终统计：
```json
{
  "run_id": "20260402T011314Z",
  "inputs": { "category_url": "...", "max_category_pages": 1, "max_products": 1 },
  "stats": {
    "category_success": 1,
    "category_failed": 0,
    "products_discovered": 52,
    "product_targets": 1,
    "product_success": 1,
    "product_failed": 0
  }
}
```

---

## MCP Server（Claude-Code 集成）

爬虫可以作为 MCP（Model Context Protocol）服务器运行，为 Claude-Code 暴露两个工具：

| 工具 | 描述 |
|---|---|
| `crawl_bestseller_list` | 第一阶段：爬取分类页面，发现 Top 50 产品链接 |
| `crawl_product_details` | 第二阶段：爬取产品详情页（异步并发） |

### Claude-Code 配置

添加到 `.claude/mcp.json`（项目级）或 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "amazon-scraper": {
      "command": "python",
      "args": ["src/mcp_server.py"],
      "cwd": "<项目根目录绝对路径>"
    }
  }
}
```

### 分阶段 CLI 用法

CLI 现在支持单独运行各阶段：

```bash
# 仅第一阶段：爬取分类页面
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase list

# 仅第二阶段：从已有运行中爬取产品详情
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase detail \
  --run-id 20260402T032433Z \
  --max-concurrency 3

# 两阶段都执行（默认，向后兼容）
python raw_amazon_spider.py \
  --category-url "https://www.amazon.com/gp/bestsellers/home-garden/3744541" \
  --phase all
```

| 新参数 | 默认值 | 描述 |
|---|---|---|
| `--phase` | `all` | `list`（仅第一阶段）、`detail`（仅第二阶段）、`all`（两阶段） |
| `--run-id` | `None` | 已有的运行 ID（`--phase detail` 时必需） |
| `--max-concurrency` | `3` | 产品详情爬取的最大并发浏览器标签数 |

---

## 已知限制

- **无结构化数据提取** — 此工具仅归档原始 HTML。解析产品标题、价格、评分等必须由单独的下游进程完成。
- **Amazon 反爬虫拦截** — 产品详情页经常被 CAPTCHA 拦截，即使使用 `StealthyFetcher`。爬虫检测并标记这些页面（`blocked: true`），但无法绕过它们。使用 `--prefer-stealth`、`--solve-cloudflare`、`--proxy` 和更大的 `--delay-ms` 值可能有帮助。
- **每次运行单个分类** — 每次调用爬取一个分类 URL。要爬取多个分类，请多次运行脚本。
- **无增量/恢复** — 每次运行都是全新的。没有检查点或恢复机制。

---

## 技术说明：懒加载问题

Amazon 畅销榜页面使用懒加载显示 Top 50 产品：
- 初始页面加载仅渲染 ~30 个产品（首屏）
- 剩余产品（第 31-50 名）通过 XHR 动态加载
- 向下滚动页面时才会触发这些 XHR 请求
- 本爬虫通过 `page_action` 回调在浏览器中模拟滚动，确保捕获完整的 Top 50

有关技术实现的更多详情，请参阅 `CLAUDE.md`。
