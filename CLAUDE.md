1. 禁止在改进项目的时候往内容里面写入仅存在当前上下文的内容。当前上下文的内容只能被当前上下文的Agent了解，不能被其他上下文的Agent了解。比如"修改了什么""对比之前如何"，这些是错误的内容，因为内容已经被改进改掉了，其它Agent根本获得不了为什么要禁止修改或者使用xxx内容，对比之前xxx如何，改进完项目都没有的东西了，提到这些内容只能说噪音。

2. Amazon 不使用 Cloudflare。Amazon 和 Cloudflare 都是互联网大厂，Amazon 有自己的 CDN 和 DDoS 防护体系（AWS Shield / CloudFront），不可能把流量交给竞争对手 Cloudflare 代理。因此抓取 Amazon 时 `solve_cloudflare` 必须默认为 `False`。开启 `solve_cloudflare=True` 会导致每次请求多耗 5-15 秒甚至超时，且毫无收益——这是已被验证的事实。

3. **Agent 调用的模型自己审核时喜欢偷懒**。当同一个 LLM 既负责执行任务又负责审核自己的产出时，它倾向于快速通过、忽略细节、敷衍了事。这就是为什么 `amazon-chunker-audit` 必须是一个**独立的 agent**（而非 chunker 的自检步骤），且**只报告不修复**——修复责任交由 orchestrator 重新触发 chunker 执行。审核与修复必须分离，否则 audit 会为了省事而隐瞒问题或虚假报告修复成功。

4. **流水线必须自动完整执行，禁止中途中断询问用户**。任何 Agent 收到触发请求后，必须按照工作流规范从头执行到底，直至 `summary.md` 输出为止，**不得在任何步骤停下来询问用户**（例如"是否要开始执行""下一步需要你确认""请告诉我是否继续""要不要生成报告"等）。遇到报错或部分失败时，记录错误信息后继续推进流水线，不得暂停等待用户回复。这条规则适用于所有 Agent：orchestrator、chunker、audit、四个 analyst。

5. 在绝大多数情况下，禁止使用try-except。遵循fail-fast原则，能第一时间报错，就第一时间报错。而不是通过try-except把问题隐藏。

6. **调试 HTML 解析问题时，直接读 raw HTML，不要只依赖 BeautifulSoup 静态解析结果**。BS4 的 `select_one` 只返回第一个匹配元素，可能遗漏后续同 ID 容器中的内容。Amazon 商品页上 Brand Story 和 Premium A+ 分属两个 `id="aplus"` 的 div，`select_one('#aplus')` 只取到第一个，导致第二个容器中的 `3p-module-b` 等模块及其大海报图全部丢失。遇到"提取不完整"的反馈时，第一步应该是 `read_file` 看 raw HTML 确认源数据完整性，而不是反复写 debug 脚本用 BS4 解析——BS4 解析结果本身就是出问题的环节，用它来验证自己没有意义。

7. **HTML 选择器和正则必须面向开放集合设计，不要枚举已知值**。Amazon A+ 模块类型不只有 `module-N`、`premium-module-N`、`brand-story-*`，还有 `3p-module-b`，未来可能出现 `np-module-*` 等任何前缀。枚举式正则每遇到一种新前缀就要改代码，应该用 `([a-z0-9]+)-module-([a-z0-9-]+)` 这样的通用模式一次性覆盖。同理，`_find_aplus_container` 返回单个元素改为 `_find_aplus_containers` 返回列表，才能容纳页面中出现多个 A+ 容器的情况。

8. **Windows 下启动外部 CLI/Agent 子进程时，必须先确认所选方案在当前事件循环实现上真实可用，不要想当然使用 `asyncio.create_subprocess_exec`**。不同 Python 版本、事件循环策略、宿主环境对 asyncio subprocess 的支持并不一致；在 Windows 上它可能直接抛 `NotImplementedError`，导致任务一启动就失败。只要目标是启动一个长时间运行的外部命令并持续读取 stdout，优先选择在目标平台上已验证可用的方案（例如 `subprocess.Popen` + 线程/异步桥接读取），不要把“理论上支持”当作“当前环境可用”。

9. **错误信息必须端到端透传，禁止在链路中任何一层把真实错误降级成“未知错误”或空字符串**。如果后端任务状态里有 `error` 字段，SSE/HTTP 接口必须把它原样传给前端；前端收到状态更新时也必须同步更新错误信息，而不是只更新 `status`。Fail-fast 不只是尽快失败，还包括让最终用户和后续 Agent 能看到**准确的失败原因**，否则排障会被无意义的“未知错误”阻塞。

10. **当同一任务可能对应多个历史/镜像 workspace 路径时，路径解析必须有稳定、可解释的 canonical 优先级，不能只靠“谁先匹配到”或“分数相同就保留旧值”**。如果存在多个候选目录都含有部分产物，必须明确规定 canonical workspace 的优先级，并在评分相同的情况下继续按优先级决策；否则系统会把任务绑定到陈旧目录，导致前端进度、断点续跑、报告读取全部指向错误位置。路径解析一旦涉及历史兼容，tie-break 逻辑必须是显式规则，不能依赖候选顺序碰运气。