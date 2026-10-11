---
name: knowline-read-papers
description: 在知序指定领域或当前选中论文范围内阅读、翻译、分析和对比论文，保留冻结版本、页码与原文证据，并自行提交成果。
---

# 论文阅读、翻译和对比

在知序项目根读取 catalog 和 view，按用户名称或当前选择定位资源。领域范围用 `app/kw.cmd tasks create --domain "名称" --type paper --task compare_resources --question "问题"`；指定部分资料时用 `app/kw.cmd jobs create --spec <JSON>`，resource_ids 必须明确。任务类型按目标选择，不将用户只要求翻译扩成综述。

读取任务 context、result-template 和 [共享协议](../../docs/PROTOCOL.md)，确认冻结 PDF 版本与哈希。阅读正文、方法、实验及相关图表；没有正文、公式或图像证据时明确限制。扫描页需 OCR 或视觉阅读，不把空文本认作论文没有内容。

分析区分论文原有结论、跨论文比较和你的推论。比较同一问题下的假设、数据、方法、限制与实现条件，不凭引用次数判断方法优劣。翻译保留公式、图表号、术语与引用位置；解释附在译文之外。代码关联必须有代码行或明确原始仓库证据。

产物写入任务 output_dir。事实陈述在 schema_version=2 的 claims 中附 resource_id、version_id、零起始 page_index 和可复现原文 quote。原文定位保持原语，不能将中文译文当作英文 PDF 引文。图片解读注明图号、页码和观察/推断边界。

计算实际产物 SHA-256，填写 result.json，然后由 智能体 自行执行 `app/kw.cmd jobs ingest <job_id> --manifest <实际路径> --if-revision <revision>`。校验失败就回到源文修正；冲突重读任务，不让用户复制指令或搬运结果。展示任务结果并说明证据局限。

自动桥执行时，以任务提示中的自动回流规则为准：写 result.json 后退出，由知序执行 claim/ingest 与校验，不自行重复领取或提交。接入协议见 app/docs/LOCAL_AGENT.md。
