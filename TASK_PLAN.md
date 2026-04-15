## Plan: Top50 细分类分析 + Markdown First 流水线

以 MarkItDown 作为 HTML 到 Markdown 的标准中间层，再做语义分块和结构化提取，并新增一个细分类分析 agent。该方案保持现有多 agent 编排骨架不变，只替换 chunker 主链路输入形态，最终实现 Top50 全量逐商品细分类并输出汇总表。

### Steps
1. 基线梳理与样本固化（依赖：无）
- 固化当前输出契约：chunks 目录结构、global_manifest.json、三份维度报告与 summary。
- 选 2 个代表类目做回归样本（服饰 + 非服饰），用于迁移前后对比。

2. 设计 Markdown First 中间层（依赖：1）
- 新增转换阶段：raw HTML -> canonical markdown。
- 定义每个商品的中间产物目录：raw_html、canonical_md、semantic_chunks、extract。
- 约定中间产物必须保留原始证据锚点：来源字段、片段标题、原文摘录。

3. 引入 MarkItDown 并实现转换器（依赖：2）
- 在依赖中加入 markitdown。
- 实现批量转换脚本：读取 Top50 商品 HTML，输出每个商品 canonical markdown。
- 对失败页面保留失败清单与错误原因，允许后续步骤跳过但不阻塞全局。

4. 将现有 chunker 改为 Markdown 分块（依赖：3）
- 调整 amazon-product-chunker 与 amazon-chunker skill：从基于 DOM id 切块，改为基于 Markdown 标题与语义规则分块。
- 分块目标保留原四块语义：ppd、customer_reviews、product_details、aplus，同时允许未知块落入 misc。

5. 提取器适配 Markdown 输入（依赖：4）
- 调整 amazon-extractor 及子技能读取 markdown chunk，而非仅 raw 子 HTML。
- 保持原有输出合同不变：ppd_extracted、customer_reviews_extracted、product_details_extracted、aplus_extracted。
- 对关键字段建立兜底策略：若 markdown 未提取到关键字段，则从对应原 HTML 兜底提取，避免回归。

6. 新增细分类分析 agent 与 skill（依赖：5）
- 新建 fine-grained analyst agent，输入为 Top50 的 ppd + product_details + 商品图证据。
- 分析策略：逐商品细分类判定（全类目通用），输出标准化表格。
- 输出字段至少包含：rank、asin、amazon大类、细分类标签、关键属性证据、视觉证据、置信度、是否需人工复核。

7. 将细分类分析接入编排器（依赖：6）
- 在 orchestrator Step 4 并行任务中新增 fine-grained analyst。
- 在 summary 汇总中新增“细分类结构与机会”章节。
- 保持失败隔离：任一维度失败不阻断其它维度与 summary 生成。

8. 输出契约与文件注册（依赖：7）
- 在 plugin 元数据中注册新 agent 与新 skill。
- 新增报告输出：{category_slug}_fine_grained_dim.md 与 .json。
- 在 Exit Checklist 中新增该维度产物校验。

9. 验证与对比评估（依赖：8）
- 跑 Top50 全流程（至少 1 个类目），验证所有报告与 summary 完整产出。
- 跑小样本回归（5-10 商品）做迁移前后字段对比：关键字段召回率、错误率、运行时长、token 成本。
- 人工 spot check 细分类结果，验证证据链是否可审计。

10. 文档更新与迁移说明（依赖：9）
- 更新 README、流程图、使用说明与故障排查。
- 增加“MarkItDown 转换失败/字段缺失”的处理手册。

### Decisions
- 范围：全类目通用，不限服饰。
- 粒度：Top50 逐商品分析后汇总成细分类表。
- 技术路线：MarkItDown 先转换，再分块。
- 多模态：LLM 视觉优先，用图片 + PPD 联合判定细分类。
