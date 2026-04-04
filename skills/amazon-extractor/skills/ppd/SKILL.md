---
name: ppd-extractor
description: PPD（Product Page Data）块提取器。从 ppd.html 中提取 Core/Buybox/Twister/Overview/Bullets/Images 六个子阶段的结构化数据，输出 ppd_extracted.md。当 agent 需要提取 PPD 块时调度此技能。
type: skill
---

# PPD 提取器

**输入**：`ppd.html`
**输出**：`ppd_extracted.md`
**复杂度**：复杂，6 个子阶段

## 子阶段与目标字段

### A1. Core

- Title
- Average stars
- Rating count
- Current price
- Original/List price
- Discount %
- Discount amount
- 自行发现其他可能的路径

### A2. Buybox

- Merchant ID
- Availability
- Quantity options
- Ships from / Sold by
- Returns / Payment / Packaging（若存在）
- 自行发现其他可能的路径

### A3. Style Options (Twister)

- Current selection
- 每个变体：Option name / price / discount / stock / prime status
- 输出为表格
- 自行发现其他可能的路径

### A4. Product Overview

- Key-Value 表格（品牌/材质/颜色/尺寸等）
- 主路径：`#productOverview_feature_div`
- 备选路径：`#productFactsDesktopExpander`
- 自行发现其他可能的路径

### A5. Feature Bullets

- `#feature-bullets` 下的 `<li>` 列表
- 过滤掉过短的噪声项（< 15 字符）
- 自行发现其他可能的路径

### A6. Image Assets

- 主图 + 缩略图 URL 列表
- 从 `#altImages` 或 `#imageBlock` 中提取
- 自行发现其他可能的路径

## 提取策略要求

参照 `ppd_agent_prompt_zh.md` 的完整规范：
1. **结构诊断**：描述该类目 PPD 的主要语义块及变体风险
2. **主备路径**：每个字段至少有主 selector + 备选 selector + 兜底规则
3. **价格口径**：明确当前价、原价、折扣、优惠金额的计算逻辑
4. **去重清洗**：价格文本中的重复片段（如 `$33.99 $ 33 . 99`）、空值处理
5. **缺失字段**：统一写 `N/A`，不得臆造
6. **自行发现其他可能的路径**

### ⚠️ 价格必填约束（Hard Rule）

**`Current price` 不允许为 `N/A`，必须提取到真实的购买价格。**

提取优先级（逐级 fallback）：
1. **Core 区域**的价格节点（常见 selector：`#corePrice_feature_div`, `.a-price .a-offscreen` 等）
2. **Buybox 区域**的价格节点（`#buybox`, `#newBuyBoxPrice`, `#price_inside_buybox` 等）
3. **Twister / 变体表**中当前选中项的价格
4. 自行探测页面中其他包含价格的区域

如果所有路径均未命中，才写 `N/A` 并在 manifest 中标记 `price_missing: true` 以便人工复查。

## 输出格式

```markdown
# PPD Extracted

## Core

- Title: ...
- Average stars: ...
- Rating count: ...
- Current price: $xx.xx
- Original/List price: $xx.xx
- Discount: xx%
- Discount amount: $x.xx

## Buybox

- Merchant ID: ...
- Availability: ...
- Quantity options: 1, 2, 3, ...
- Ships from: ...
- Sold by: ...

## Style Options (Twister)

- Current selection: ...

| Option | Current Price | List Price | Discount | Prime | Status |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... | ... |

## Product Overview

| Field | Value |
| --- | --- |
| Brand | ... |
| Material | ... |

## Feature Bullets

- Bullet 1 text...
- Bullet 2 text...

## Image Assets

- https://...jpg
- https://...jpg
```

## 产出

- `chunker/ppd_extract.py` — PPD 提取器实现
- `tests/test_ppd_extract.py` — PPD 提取器测试
