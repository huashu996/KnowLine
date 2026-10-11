---
name: knowline-build-knowledge
description: 按用户的层名与侧重点，由智能体理解冻结资料、构建有证据的分层知识文档和关系，验收并发布本地混合检索库。用于知序建库与增量更新，页码切块只算预处理。
---

# 知序分层知识构建

执行已安装的 `knowledge-build` 技能（默认 `~/.codex/skills/knowledge-build/SKILL.md`）。全局版本缺失时读取本目录 [项目副本](references/knowledge-build.md)，不能改用页分割假完成。

context.knowledge_layers的稳定ID、层名和focus为当前合同，支持用户任意1–12层。读取context/result-template与prepared_sources，按技能的内容、排版和证据规范深度分析，不照搬参考库成员。

自动模式只在当前output_dir生成知识文档、覆盖报告、schema_version=2 result.json后退出，不自行ingest/assemble。平台检查冻结版本、引文、层覆盖与检索测试，随后发布知识和混合索引。手动模式用项目docs/KNOWLEDGE_CARDS.md的公共工具，不直接写SQLite。

知识长任务不采用论文检索600秒限时。只创建目录、分PDF页或重复摘句不能声称知识完成；事实、综合、推断和研究设想明确区分，按真实状态回流。

完整分析的高效定稿、缓存、失败恢复与耗时报告执行 [高效完整构建合同](references/performance.md)。在支持 v3 的知序使用一次 authored analysis 加可信渲染工具，避免模型重复生成相同正文；平台仍检查全部原验收题。没有工具的独立知识任务遵循同样去重、证据和计时原则，不声称执行了不可用脚本。

自动桥执行时，以任务提示中的自动回流规则为准：写 result.json 后退出，由知序执行 claim/ingest 与校验，不自行重复领取或提交。接入协议见 app/docs/LOCAL_AGENT.md。
