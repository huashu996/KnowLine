# 项目级本地智能体接入

一次连接、持久绑定、自动恢复和工具执行协议见 [LOCAL_AGENT.md](LOCAL_AGENT.md)。自动桥模式由平台领取与校验回流，执行器只写本任务结果清单。

# UI 与本地智能体共享协议

模型执行由本项目连接的本地智能体客户端完成。智能体首先读取 `resource/workspace/catalog.json` 和 `resource/workspace/view.json`，按领域/知识库名称确定范围；写入使用项目 `app/kw.cmd`，由同一个本地单写服务完成。这里的 HTTP 是本地数据同步协议，不是大模型 API。详细连接与执行流程见 [LOCAL_AGENT.md](LOCAL_AGENT.md)。

`kw domains list/show` 和 `kw project catalog/state` 可离线读取发布快照；`kw import --path ... --domain ...` 在登记后加入指定领域；`kw tasks create --domain ...` 冻结该领域选定类型的资料；`kw project view` 发布软件导航请求。名称或别名出现多个匹配时返回 `name_ambiguous`，不会默认选第一个。

导航由 `/project/view` 提交并以 navigation 事件通知界面。界面自身的页面/选择变化记录为 view_state，避免回声使阅读位置重置。未保存编辑不会被外部导航丢弃，界面提示用户保留编辑或确认切换。

所有接口通过 `http://127.0.0.1:<port>/api/v1` 访问。服务只绑定 loopback，检查 Host 与 Origin；不开放跨域。`GET /session` 提供本会话令牌。变更携带 `X-KW-Token`、唯一 `operation_id`，已存在实体的变更同时携带 `base_revision`。文件变更还需 `base_sha256`、`version_id`；PDF 还需页面几何哈希。

同一 `operation_id`、同一请求重试返回已提交结果；不同请求复用操作 ID 返回冲突。稳定错误格式为 `{"code":"revision_conflict","params":{"current_revision":2}}`。`GET /events?after=<sequence>` 提供 SSE 事件，事件只含类型、ID、revision 和 sequence；客户端随后读取正式记录。重连可以补读历史事件。

资源 ID 是 UUID，独立于路径和字节哈希。`type` 可为 paper、code、link；paper ID 沿用资源 ID。分组和知识库使用成员表，不复制或移动文件。知识库带独立 revision、member_revision、index_state 和 build_id。查询必须提交 kb_id 与当前 kb_revision，候选 SQL 同时约束成员、版本和资源状态；未选资源不能进入检索或图。

## 任务上下文

创建 `POST /jobs` 请求中的 `resource_ids` 必须显式给出。可带 `kb_id`；此时资源必须是该知识库成员。`task`、`question` 和可选 `skill` 指定人工执行的目标。skill 名称必须在可信盘点中存在。输出写入 `.knowledge/jobs/<job_id>/context.json` 和 `result-template.json`。

```json
{
  "schema_version": 2,
  "job_id": "j_<uuid>",
  "task": "literature_review",
  "scope": {"resource_ids": ["r_<uuid>"], "kb_id": "kb_<uuid>", "kb_revision": 1},
  "resources": [{
    "resource_id": "r_<uuid>", "type": "paper", "version_id": "v_<uuid>",
    "snapshot_path": ".knowledge/versions/r_<uuid>/v_<uuid>.pdf",
    "sha256": "<actual sha256>",
    "annotations_path": ".knowledge/jobs/j_<uuid>/r_<uuid>-annotations.json"
  }],
  "question": "根据这些论文写综述并附原文证据",
  "external_network": "off",
  "allowed_actions": ["read_selected", "write_job_outputs"],
  "output_dir": "outputs/资料解读_论文主题_2026-10-11_001350",
  "execution_mode": "manual"
}
```

输出目录使用任务名称、主题、来源页码（适用时）与北京时间；同名同秒任务加序号区分。任务编号以 `context.job_id` 为准。历史 `outputs/j_<uuid>` 与 `resource/outputs/j_<uuid>` 由持久路径映射解析，冻结上下文、结果清单和产物哈希保持不变；程序访问历史文件应使用 `backend.safety.contained(project, path)`，外部工具使用任务指令中的实际绝对路径。

代码条目另外提供安全清单和 allowed_files，目录资源还提供 tree_sha256。快照 ZIP 的字节哈希与目录树哈希是不同字段。所有协议路径相对项目根，代码文件路径相对版本内代码根。硬链接不作为不可变版本。

## 结果回流

先读取同目录模板。至少提供一个实际产物；每项包括类型、project-relative 路径和文件 SHA-256。事实 claims 每项必须有 evidence。示例中的 ID 和引文是占位合同，不能作为实际结果提交。

规范提交使用 `status=completed`；只完成部分范围时另设 `partial=true` 并列明 warnings。兼容 `status=partial` 的已有成果，仍校验全部产物哈希、冻结范围、版本、PDF 和证据，回流状态由实际成果决定。候选导入必须逐一覆盖全部冻结 candidate_id：成功项给出资源 ID、版本与哈希，缺项给出 unavailable_reason；零可用全文显示失败。可用 `app/scripts/research_finalize.py <context.json> <output_dir/analysis.json>` 对已完成的分析清单生成规范结果与真实哈希。

```json
{
  "schema_version": 2,
  "job_id": "j_<uuid>",
  "status": "completed",
  "artifacts": [{"type":"review", "path":"outputs/j_<uuid>/review.md", "sha256":"<actual sha256>"}],
  "claims": [{"claim_id":"claim_1", "text":"有来源的陈述", "evidence":[{
    "resource_id":"r_<uuid>", "version_id":"v_<uuid>", "page_index":0, "quote":"Actual source passage"
  }]}],
  "proposed_relations": [], "warnings": []
}
```

代码 evidence 使用 `file`、`file_sha256`、`line_start`、`line_end` 和 `quote`。PDF 页从 0 开始，代码行从 1 开始且闭区间；统一 CRLF/CR 到 LF，不把软换行当成新行。引文允许空白规范化后比较，其余内容必须复现。

结果清单以临时文件写完，再替换 `.knowledge/jobs/<job_id>/result.json`。使用 `kw jobs ingest` 提交。API 的 manifest 字符串相对该 job 目录；CLI 的 `--manifest` 是从当前工作目录读取的真实 JSON 文件，它把内容提交给服务。校验检查产物目录、哈希、输入快照、选择范围、版本、页/行和引文。失败不会把任务设为 completed；AI 建议关系只有待审核状态。原文件已更新时，结果仍归旧快照并列出新版本提醒。

本协议规定输入范围，不等于操作系统沙箱。人工启动的智能体需单独配置实际读取/输出权限和模型服务；平台不自动加载资料内 AGENTS.md、CLAUDE.md、hooks 或 MCP 配置，不关闭审批，不自动外发正文。

## PDF 批注

`POST /resources/<id>/annotations` 的 annotation 包含 kind=highlight/text、page_index、page_geometry_hash、comment、color。高亮使用逐行 quads，点序为 upper-left、upper-right、lower-left、lower-right，坐标空间为 `mupdf_unrotated_v1`。便签用 point。修改/删除携带已有 annotation_id 和 action=update/delete。

前端用 PDF.js viewport 逆矩阵还原 PDF 用户空间，再使用后端页面 pdf_to_mupdf 矩阵。保存真实 PDF Highlight/Text 对象后读取引擎生成的 /NM；应用 UUID、/NM 和本版本 xref 分开记录，xref 不作为稳定身份。签名、权限受限文档禁止写入。不同页面选区需分别保存；连续阅读器允许滚轮跨页；一次选区仍限定在同一页，保存使用选区页和冻结几何，不使用滚动后的当前页。

## 安全限额

ZIP 最多 10,000 条目，声明解压总量 256 MiB，单文件 16 MiB，预览 2 MiB，压缩比不超过 300。实际读取再次计数；不递归解压嵌套包。路径穿越、盘符、UNC、ADS、设备名、链接、特殊文件、重复、大小写与 NFC 碰撞均拒绝。检查 orig_filename，避免 Windows zipfile 在读取时规范化危险反斜杠。私钥、.env、控制目录及智能体配置不会进入正文索引和任务白名单。

请求体限额 2 MiB，导入 PDF/ZIP 限额 128 MiB；外部链接和 README 图片不自动联网。日志不记录会话令牌和私密请求体。

分层配置与图像卡片的组装合同见 [KNOWLEDGE_CARDS.md](KNOWLEDGE_CARDS.md)。ready 表示原文索引，organized 表示当前版本已提交卡片，两者单独显示。
