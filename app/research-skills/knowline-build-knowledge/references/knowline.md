# 知序交接

优先使用当前项目 app/research-skills/knowline-build-knowledge/SKILL.md。冻结 context.knowledge_build.research_contract 为 evidence-to-experiment-v4 的任务遵循 [v4合同](research-contract.md)，不加载历史备份技能。

context.resources 冻结资料版本、哈希与范围；knowledge_layers 冻结用户层；knowledge_build.prepared_sources 提供完整正文/代码。一次写 output_dir/knowledge-analysis.json，由 app/scripts/knowledge_finalize.py 生成分层文档、覆盖报告、真实哈希和 schema_version=2 result.json。

自动任务生成清单后退出，由平台 ingest/assemble；手动任务通过 kw 或公共 API。原文预索引 ready 仅表示预处理完成；knowledge_state=organized 才表示知识及双路检索验收完成。不得直接写数据库、修改冻结 context/result 或原始证据。

v4 对方法前提/失败、主张引用、多层归属和30–50题逐项验证。旧冻结合同继续按其原版本处理；更新来源须重新验证全部证据。恢复与真实计时见 [performance.md](performance.md)。
