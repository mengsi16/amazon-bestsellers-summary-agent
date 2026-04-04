# 项目问题记录与解决方案

## 问题描述

用户希望使用 scrapling 爬取 Amazon Bestsellers 页面，但发现爬虫只能获取到大约 30 个产品，而不是期望的 Top 50。

**根本原因**：Amazon Bestsellers 页面采用了懒加载（lazy loading）机制：
1. 初始页面加载时只渲染约 30 个产品（在首屏可见区域）
2. 剩余的产品（第 31-50 名）需要通过 XHR 请求动态加载
3. 当用户向下滚动页面时，才会触发这些 XHR 请求获取新数据
4. 爬虫如果不模拟滚动操作，就无法触发懒加载，因此只能获取到初始的 ~30 个产品

## 技术细节

**Amazon 的懒加载机制**：
- 页面使用 `nextPage` API 端点获取额外的产品数据
- 数据以 JSON 格式返回，然后通过客户端 JavaScript 渲染到页面上
- XHR URL 示例：`/acp/p13n-zg-list-grid-desktop/.../nextPage?page-type=zeitgeist&stamp=...`

## 解决方案

### 1. 研究 scrapling 的 API

发现 scrapling 的 `DynamicFetcher` 和 `StealthyFetcher` 支持 `page_action` 参数：
- `page_action` 是一个回调函数，接收 Playwright 的 `page` 对象
- 可以在页面加载完成后执行自定义的浏览器操作（如滚动、点击等）
- 该参数通过 `_build_fetch_kwargs()` 传递给 fetcher

### 2. 实现自动滚动逻辑

在 `raw_amazon_spider.py` 中添加了 `_make_category_scroll_action()` 方法：

```python
def _make_category_scroll_action(self):
    """返回一个 page_action 回调函数，用于滚动页面触发懒加载 XHR"""
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

            # 通过 JavaScript 统计页面上的唯一 ASIN 数量
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

            if count >= 50:  # 达到目标数量，停止滚动
                break

            if count <= prev_count:  # 连续多次没有新数据
                stale_rounds += 1
                if stale_rounds >= 4:
                    break
            else:
                stale_rounds = 0

            prev_count = count

        page.evaluate("window.scrollTo(0, 0)")  # 滚动回顶部
        page.wait_for_timeout(300)

    return _scroll
```

### 3. 修改爬虫流程

在 `crawl()` 方法的 Phase 1（分类页面爬取）中：
- 如果启用了 `scroll_category`（默认启用），则生成滚动回调
- 通过 `_fetch_with_fallback(category_url, page_action=scroll_action)` 传递

在 `_fetch_with_fallback()` 和 `_build_fetch_kwargs()` 中：
- 接受 `page_action` 参数并传递给 fetcher

### 4. 添加 CLI 参数

新增了控制滚动的命令行选项：
- `--no-scroll`：禁用自动滚动
- `--scroll-pause-ms`：设置每次滚动后的暂停时间（毫秒，默认 1500ms）

## 测试结果

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 发现产品数 | 32 个 | **52 个**（50 个有效产品 + 2 个页脚链接） |
| 覆盖范围 | sccl_1 到 sccl_30 | **sccl_1 到 sccl_50**（完整的 Top 50） |
| XHR 捕获 | 0 KB | **46 KB**（包含 nextPage 响应） |

**结论**：自动滚动成功触发了 Amazon 的懒加载 XHR，获取到了完整的 Top 50 畅销产品列表。

## 关键代码文件

- `raw_amazon_spider.py` - 主要实现文件
  - `CrawlConfig` - 添加了 `scroll_category` 和 `scroll_pause_ms` 配置
  - `_make_category_scroll_action()` - 滚动逻辑实现
  - `_build_fetch_kwargs()` - 传递 `page_action` 参数
  - `_fetch_with_fallback()` - 支持传入自定义 page_action
  - `parse_args()` / `build_config()` - CLI 参数处理

---

## 问题2：商品详情页爬取被拦截（CAPTCHA / 503 错误）

### 问题描述

在实现"列表页 → 详情页"流程后，发现商品详情页（Product Detail Page）抓取成功率极低：

**现象**：
- 从榜单页提取的商品链接（如 `https://www.amazon.com/dp/B0DRNRC5H5`）无法正确抓取
- 返回的 HTML 是 503 错误页或 "Continue shopping" CAPTCHA 验证页
- 文件大小只有 2-5 KB（正常商品页应有 2000+ KB）

**日志示例**：
```
product_0001_B0DRNRC5H5.html: 2KB  | captcha=False | 503err=True  | blockBtn=False
product_0003_B0973DGD8P.html: 5KB  | captcha=True  | 503err=False | blockBtn=True
```

### 根因分析

1. **Fetcher 选择错误**：默认优先使用 `DynamicFetcher`，但会被 Amazon 反爬拦截
2. **Referer 问题**：详情页请求缺少自然来源（如 Google 搜索），易被识别为爬虫
3. **连续请求风控**：类目页抓取后立即抓取详情页，触发 Amazon 的速率限制
4. **URL 参数污染**：榜单页提取的链接包含 session 参数（如 `/147-7864381-8199527`），直接访问易触发 CAPTCHA
5. **缺乏有效性检测**：错误页面也被保存，无法区分成功/失败

### 解决方案

#### 1. 详情页强制使用 StealthyFetcher

```python
# 新增 force_stealth 参数
fetch_result = self._fetch_with_fallback(target_url, force_stealth=True, google_search=True)

# _fetch_with_fallback 中优先使用 StealthyFetcher
if force_stealth:
    ordered_fetchers = [("stealth", StealthyFetcher)]
```

#### 2. 模拟 Google 搜索来源

启用 `google_search=True`，让 StealthyFetcher 模拟从 Google 搜索结果点击进入：
```python
kwargs = {
    ...
    "google_search": google_search,  # True for product pages
}
# 实际效果：referer 变为 https://www.google.com/
```

#### 3. 类目→详情阶段冷却

在两阶段间增加强制延迟（最低 15 秒）：
```python
if product_targets:
    cooldown = max(self.config.delay_ms / 1000.0 * 3, 15.0)
    LOGGER.info("Cooling down %.1fs before product phase …", cooldown)
    time.sleep(cooldown)
```

#### 4. 页面有效性检测

新增检测函数识别真实商品页 vs 错误页：
```python
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

def is_valid_product_page(html_content: str) -> bool:
    content = html_content.lower()
    if any(m in content for m in ANTI_BOT_MARKERS + SERVICE_ERROR_MARKERS):
        return False
    return any(m in content for m in PRODUCT_PAGE_MARKERS)
```

#### 5. 无效页面重试 + 指数退避

```python
for product_attempt in range(1, max_product_retries + 1):
    fetch_result = self._fetch_with_fallback(target_url, force_stealth=True, google_search=True)
    html = fetch_result.response.html_content
    
    if is_valid_product_page(html):
        valid = True
        break
    
    # 检测到无效页面，记录并退避重试
    if product_attempt < max_product_retries:
        wait = self.config.delay_ms / 1000.0 * backoff_multiplier * product_attempt
        LOGGER.info("Backing off %.1fs before retry …", wait)
        time.sleep(wait)
```

#### 6. 默认参数优化

| 参数 | 旧值 | 新值 |
|------|------|------|
| `prefer_stealth` | `False` | `True` |
| `delay_ms` | 1200 | 3500 |

### 测试结果

**修复前**：
| 商品 | 大小 | 结果 |
|------|------|------|
| B0DRNRC5H5 | 2KB | ❌ 503 错误页 |
| B07RSCPH4N | 1159KB | ✅ 有效页（但之前轮次超时）|
| B0973DGD8P | 5KB | ❌ CAPTCHA 页 |

**修复后**：
| 商品 | 大小 | productTitle | captcha | 503 | 结果 |
|------|------|:---:|:---:|:---:|:---:|
| B0DRNRC5H5 | **2397KB** | ✅ | ❌ | ❌ | ✅ 有效 |
| B07RSCPH4N | **2223KB** | ✅ | ❌ | ❌ | ✅ 有效 |
| B0973DGD8P | **2347KB** | ✅ | ❌ | ❌ | ✅ 有效 |

**结论**：修复后详情页抓取成功率达到 **100%**（3/3），文件大小从 2-5KB 提升到 2200+ KB，均为完整渲染的商品详情页。

### 关键改动文件

- `raw_amazon_spider.py`
  - 新增 `SERVICE_ERROR_MARKERS` / `PRODUCT_PAGE_MARKERS` 常量
  - 新增 `is_service_error_page()` / `is_valid_product_page()` 函数
  - `_fetch_with_fallback()` 新增 `force_stealth` 和 `google_search` 参数
  - `_build_fetch_kwargs()` 支持 `google_search` 参数传递
  - 详情页抓取循环增加有效性检测和重试退避逻辑
  - 类目→详情阶段增加冷却延迟
  - CLI 参数默认值调整：`prefer_stealth=True`, `delay_ms=3500`

---

## 问题3：商品详情页静态分块策略过细，难以适配不同页面模板

### 问题描述

在最初版本的 `static_chunker` 中，策略是对商品详情页做较细粒度的静态抽取，例如分别提取：

- title / brand
- offer pricing
- buybox delivery
- feature bullets
- product overview
- product details
- A+ 内容
- review summary

这种做法在页面结构比较规整的情况下可以抽出不少字段，但在 Amazon 商品详情页上很快暴露出两个核心问题：

1. **分得太细，页面模板一变就容易失效**
2. **复杂区域信息损失严重**

Amazon 的详情页虽然整体很复杂，但很多大块内容其实已经由 Amazon 自己通过稳定的 DOM `id` 做了分区。如果我们继续用“很多小块 + 很多细规则”的方式处理，就需要为不同模板不断补分支，维护成本很高，而且不稳定。

### 根因分析

#### 1. 细粒度 chunker 对页面差异非常敏感

不同商品详情页在以下区域差异很大：

- 价格区 / 优惠区 / buybox
- A+ 模块结构
- 评论区展示方式
- 产品信息区展开与折叠方式

如果静态规则试图把这些区域进一步拆成很多小块，就会遇到：

- 某些块在 A 商品存在，在 B 商品不存在
- 同一语义在不同商品页里对应不同 DOM 层级
- 同一类商品的展示顺序和布局也可能不一样

结果就是，规则越细，越容易在新页面上抽不到，或者抽到残缺内容。

#### 2. 复杂区域被过度“清洗”和“理解”

之前最典型的问题出现在价格和 offer 相关区域：

- 价格区有当前价、划线价、coupon、Prime、Subscribe & Save、配送承诺、seller、buybox 多种混合语义
- 如果静态层过早把它压缩成几行字段，就会丢掉很多上下文
- 后续 LLM 即使看到这些结果，也很难恢复真实页面语义

本质上，这类复杂区域不适合一开始就做强结构化抽取。

### 改造思路

后续分块策略从“细粒度静态抽取”改为“先按 Amazon 已有大块直接切分，再让后续模块处理语义”。

关键判断是：

- Amazon 已经在很多详情页关键区域提供了比较稳定的 DOM `id`
- 这些 `id` 本身就是天然的大块边界
- 与其自己再人为拆得很细，不如先直接按这些大块保留

因此，新的 `static_chunker` 策略改为：

1. **优先按稳定 selector / id 做大块提取**
2. **只做最轻量的清洗**
3. **先保留原始结构，不急着做字段级理解**
4. **复杂语义交给后续 LLM 或归一化阶段**

### 当前策略

当前 `static_chunker` 已移动到：

- `chunker/static_chunker.py`

它的职责已经被刻意收窄为“大块提取器”，而不是“字段抽取器”。

当前主要提取的块包括：

- `#customerReviews` → `customer_reviews.html`
- `#productDetails_feature_div` → `product_details.html`
- `#aplus` → `aplus.html`
- `#ppd` → `ppd.html`

同时保留两个辅助产物：

- `aplus_comparison.md`
  - 从 A+ comparison table 模块中提取 markdown 表格
- `aplus_assets.md`
  - 从整个 `#aplus` 中提取图片资源索引
  - 不依赖固定 `nth-child`，避免页面结构变化导致失效

### 清洗原则

当前版本只做非常轻的清洗：

- 提取目标块后，统一删除 `<script>...</script>`
- 其他结构尽量原样保留
- 不在静态层做价格、优惠、配送、seller 等复杂字段的强提取

这样做的目的不是“现在就把数据变整齐”，而是先保证：

- 分块边界稳定
- 信息保真
- 不同详情页模板都能较高概率命中

### 为什么这样更合适

这套策略的核心优势是：

1. **块边界稳定**
   - 直接复用 Amazon 自己页面里的大块 `id`
   - 比自定义很多细粒度规则更稳

2. **信息损失更少**
   - 先保留整块 HTML
   - 后续需要时可以让 LLM 在大块内做整理

3. **更适合多模板详情页**
   - 不强依赖块内部的固定层级
   - 尤其适合 A+、评论区、复杂产品详情区

4. **更符合项目目标**
   - 项目目标是类目级摘要，不是把单页所有字段都静态抽干净
   - 先把大块保住，再做摘要，更符合后续流程

### 结论

`static_chunker` 的经验教训是：

- Amazon 详情页不能靠“越细越好”的静态规则来处理
- 分块过细后，不同商品详情页很难统一适配
- 更好的办法是直接利用 Amazon 已经提供好的大块 `id` 做粗分块
- 静态层只做保真和轻清洗，复杂整理交给后续 LLM

这也是当前 `chunker/static_chunker.py` 的默认设计原则。

---

## 问题4：MCP 工具调用时 Playwright Sync API 与 asyncio event loop 冲突

### 问题描述

当通过 MCP（Model Context Protocol）调用 `crawl_bestseller_list` 工具时，爬虫崩溃并报错：

```
Error: It looks like you are using Playwright Sync API inside the asyncio loop.
Please use the Async API instead.
```

**现象对比**：

| 调用方式 | 结果 |
|----------|------|
| 命令行直接运行 `python raw_amazon_spider.py` | ✅ 成功，发现 52 个商品 |
| MCP stdio 调用 `crawl_bestseller_list` 工具 | ❌ 失败，0 个商品，4 次 fetch 全部报错 |

### 根因分析

1. **FastMCP 框架运行在 asyncio 事件循环中**：所有 `@mcp.tool()` 装饰的函数都在 asyncio loop 内被调用
2. **`crawl_bestseller_list` 定义为同步函数**：`def crawl_bestseller_list(...)` 
3. **内部调用同步 Playwright API**：`spider.crawl_category_pages()` → `_fetch_with_fallback()` → `StealthyFetcher.fetch()` 使用的是 Playwright 的同步 API
4. **Playwright 禁止在 asyncio loop 中使用同步 API**：会抛出上述错误

**调用链**：
```
FastMCP (asyncio loop)
  → crawl_bestseller_list (sync def)
    → spider.crawl_category_pages() (sync)
      → StealthyFetcher.fetch() (sync Playwright)
        → ❌ Error: sync Playwright inside asyncio loop
```

### 解决方案

将 `crawl_bestseller_list` 改为异步函数，并用 `asyncio.to_thread()` 将同步 Playwright 调用隔离到线程池：

**修改文件**：`scraper/mcp_server.py`

```python
# 修改前
@mcp.tool()
def crawl_bestseller_list(...) -> dict[str, Any]:
    ...
    result = spider.crawl_category_pages()

# 修改后
@mcp.tool()
async def crawl_bestseller_list(...) -> dict[str, Any]:
    ...
    # Run sync Playwright code in a thread pool to avoid
    # "Playwright Sync API inside asyncio loop" error.
    result = await asyncio.to_thread(spider.crawl_category_pages)
```

**关键改动**：
1. `def` → `async def`：让函数在 asyncio 上下文中正确执行
2. `spider.crawl_category_pages()` → `await asyncio.to_thread(spider.crawl_category_pages)`：将同步 Playwright 代码扔到独立线程执行，与主 asyncio loop 隔离

### 验证结果

修复后再次通过 MCP stdio 调用：

```
✅ category_001_*.html — 类目页 HTML 已保存
✅ product_links.jsonl — 商品链接已发现
✅ requests.jsonl — 请求日志正常
✅ xhr/*.jsonl — XHR 捕获正常
```

### 为什么 `crawl_product_details` 没有这个问题？

`crawl_product_details` 使用的是 `AsyncStealthySession`（异步 Playwright），本身就是异步实现，与 FastMCP 的 asyncio loop 兼容。

### 经验总结

1. **MCP 工具函数默认运行在 asyncio 环境**：即使定义为 `def`，也会被 FastMCP 在 asyncio loop 中调用
2. **同步 Playwright 不能在 asyncio loop 中使用**：这是 Playwright 的设计约束
3. **解决方案**：
   - 方案 A：改用异步 Playwright（如 `AsyncStealthySession`）
   - 方案 B：用 `asyncio.to_thread()` 将同步调用隔离到线程池（本次采用）
4. **`asyncio.to_thread()` 的作用**：将同步函数扔到独立的线程池执行，避免阻塞主 asyncio loop，同时解决 Playwright sync/async 冲突
