# v4：证据到实验合同

新 context.knowledge_build.research_contract = evidence-to-experiment-v4。schema_version 仍为2；旧冻结任务保留旧合同。knowledge-analysis.json 包含 knowledge_cards、knowledge_build_report、knowledge_relations、warnings，使用知识定稿工具生成产物。

为减少重复输出，analysis 可增加 evidence_catalog:{证据ID:完整证据对象}，所有 evidence/expected_evidence 数组及 execution_log 可用证据ID字符串引用，也可继续使用完整对象。knowledge_finalize.py 在提交前确定性展开为完整证据对象，未知ID会报错；不修改原始分析文件，不降低来源验证要求。每段真实引文只需生成一次，禁止登记占位或伪造来源。

analysis 中方法卡只需写已知/推断的 method_profile 字段；定稿工具把其余字段统一补为 `{value:null,status:unknown,claim_ids:[]}`，完整结果仍含15字段。它不会补造事实或推测实现。每张卡正文与主张各承担说明/可追溯判断用途，避免同一段分析反复复制；整套方法卡、层覆盖、30–50题和关键原文不能省略。

## 卡片

保留 id/layer_id/title/content/evidence/links/claim_type/topic/terms/aliases。content 为至少160字符的实质分析，不能用占位或重复摘句凑长。新增：
- layer_ids：所属层ID数组，包含主 layer_id；覆盖报告的每层 card_ids 应包含所有归属该层的卡。
- card_kind：concept / method / experiment / failure / research_idea。
- claims：至少一条 `{id,text,claim_type,verification,evidence}`；evidence 使用卡片 evidence 中的真实项。claim_type 为 source_fact/synthesis/inference/research_idea。
- verification：paper_claim（论文原文）、code_present（代码真实存在）、execution_reported（冻结JSON运行日志报告通过）、unverified。execution_reported 还需 execution_log 为 evidence 中的代码文件证据，文件JSON有 exit_code:0、command、environment；只表示日志报告，不等于知序复现。
- method_profile：仅方法卡必填。problem/mechanism/inputs/outputs/coordinate_frame/time_semantics/objective/assumptions/labels/training_data/resources/valid_conditions/failure_conditions/hyperparameters/code，每项为 `{value,status,claim_ids}`。status=unknown 时 value:null、claim_ids:[]；source_reported/inferred 则绑定本卡主张。source_reported 只能由已定位 source_fact 支持。
- code 已知时 value 为 `{commit,file,function,config,test_entry,run_status}`，未知子项用null；run_status=not_run/log_reports_pass/log_reports_failure。提交ID未知不能从当前目录猜测。
- failure 卡的 failure_signature 是稳定字符串标识；机制、触发条件和观察来源写在正文/主张，也可另存 failure_details。已有结构化 failure_signature 会完整保留到 failure_details，再按证据和细节生成稳定标识；未知/设想失败不能写成实验已观察事实。

定稿与完整检查点恢复只允许保守规范化：整卡标签不得比其中最不确定的主张更强；有推断的整卡降为推断，逐条主张、正文和原文证据保持不变，变化记入 normalization_log。事实主张仍可单独召回，卡片始终用于知识导航，结论的事实依据必须展开并核对原始证据。规范化不能修补假引文、伪造运行结果或绕过验收。

例如一个方法同时属于基础与系统层：
```json
{"id":"method-a","layer_id":"layer_1","layer_ids":["layer_1","layer_2"],"card_kind":"method","claim_type":"source_fact","claims":[{"id":"c1","text":"来自实际阅读的具体判断","claim_type":"source_fact","verification":"paper_claim","evidence":["用实际证据对象替换本字符串"]}],"method_profile":{"coordinate_frame":{"value":null,"status":"unknown","claim_ids":[]}}}
```
示例仅说明新增字段；正式提交填全内容与15个方法字段，禁止提交示例占位。

## 证据

论文：resource_id/version_id/page_index/quote。代码：resource_id/version_id/file/file_sha256/line_start/line_end/quote。原文必须在冻结快照中逐字可找到。公式候选只有实际看图后才可说视觉核实；数字比较需注明数据集、划分、指标定义、预算和测量条件，条件不一致不能作公平优劣结论。

## 评测

knowledge_build_report 保留 layers/resources/limitations。layers 每项为 `{layer_id,status,card_ids}`，status 为 covered（列全归属该层的卡片）或 insufficient_source（增加具体 reason）。resources 逐项覆盖全部冻结资料，包含 resource_id/version_id/analyzed_pages/limitations，analyzed_pages 为实际阅读的零起始物理页数组。queries 为30–50个不同的真实问题，每项：
```json
{"query":"具体科研问题","language":"zh","category":"comparison","expected_card_ids":["实际卡ID"],"expected_evidence":["真实证据对象"],"answer_checks":["引用是否支持比较","数据集、划分和预算是否相同"]}
```
category 包括 comparison/formula/code/conflict/unanswerable/research_design/method/limitations；不适用的类别放 evaluation_not_applicable:[{category,reason}]。至少有中英问题。unanswerable 的两种 expected 数组都为空，增加 missing_evidence_reason；不得为通过评测把有答案改成无答案。

每题可指定 purpose=evidence/inspiration；默认事实检索，research_design 类默认灵感检索。设想和推断可作为方案题的预期卡，但仍需检索真实 expected_evidence，不能把灵感卡当事实依据。普通比较/公式/事实题不得依赖设想卡证明结论。

平台检查所有关键来源召回，而非top10中命中一张卡。检索分数不证明支持关系；无答案题的正确拒答、引用支持度、条件可比性、接口兼容与实验可执行性由真实答案评审完成，报告不能把这些标成自动通过。记录查询时长、重排是否真实启用、推理次数和本地/远程成本。

## 模型与查新边界

当前默认嵌入模型继续使用已装BGE。可信 app/.semantic-models/reranker/{model.onnx,tokenizer.json,config.json} 可提供经过验证的 ONNX cross-encoder；config.format=onnx_cross_encoder，含 model_id/max_length/pad_id/pad_token/positive_label_index。无模型则显式回退RRF。Qwen3生成式重排不是这个ONNX分类器的同义格式，不能改个名字冒充；需准备官方兼容运行时/权重，拿同一30–50题对照后再启用。

方案查新默认限定所选冻结资料；完整外部查新需要另有明确联网与来源授权。只能称已有方法迁移、增量改进或本次检索范围内未见同方案，不能保证首创。
