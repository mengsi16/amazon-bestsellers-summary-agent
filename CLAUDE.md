1. 禁止在改进项目的时候往内容里面写入仅存在当前上下文的内容。当前上下文的内容只能被当前上下文的Agent了解，不能被其他上下文的Agent了解。比如"修改了什么""对比之前如何"，这些是错误的内容，因为内容已经被改进改掉了，其它Agent根本获得不了为什么要禁止修改或者使用xxx内容，对比之前xxx如何，改进完项目都没有的东西了，提到这些内容只能说噪音。

2. Amazon 不使用 Cloudflare。Amazon 和 Cloudflare 都是互联网大厂，Amazon 有自己的 CDN 和 DDoS 防护体系（AWS Shield / CloudFront），不可能把流量交给竞争对手 Cloudflare 代理。因此抓取 Amazon 时 `solve_cloudflare` 必须默认为 `False`。开启 `solve_cloudflare=True` 会导致每次请求多耗 5-15 秒甚至超时，且毫无收益——这是已被验证的事实。

3. **Agent 调用的模型自己审核时喜欢偷懒**。当同一个 LLM 既负责执行任务又负责审核自己的产出时，它倾向于快速通过、忽略细节、敷衍了事。这就是为什么 `amazon-chunker-audit` 必须是一个**独立的 agent**（而非 chunker 的自检步骤），且**只报告不修复**——修复责任交由 orchestrator 重新触发 chunker 执行。审核与修复必须分离，否则 audit 会为了省事而隐瞒问题或虚假报告修复成功。