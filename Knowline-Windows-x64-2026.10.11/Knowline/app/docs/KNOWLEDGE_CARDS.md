# 分层知识卡片合同

界面建库先填写层数（1–12）、各层名称与侧重点。原文索引由本地工具生成；语义整理在当前 Codex 会话完成。服务不会调用模型。旧库可以继续原文检索，增加层级配置后才进行卡片组装。

创建任务的 JSON 含 `resource_ids`、`kb_id`、`task` 和 `question`。context 返回 `knowledge_layers`，每层具有稳定的 `layer_1` 等 ID。结果清单保持 schema_version=2，在 artifacts、claims、proposed_relations 之外增加：

```json
{
  "knowledge_cards": [{
    "id": "system-diagram",
    "layer_id": "layer_4",
    "title": "有来源的系统框图",
    "content": "按图及论文正文解释模块关系和适用条件。",
    "evidence": [{"resource_id":"<真实ID>","version_id":"<冻结版本>","page_index":0,"quote":"<该页真实原文>"}],
    "links": ["fundamental-concept"],
    "figure": {"resource_id":"<真实ID>","version_id":"<冻结版本>","page_index":0,"rect":[40,80,540,350]}
  }]
}
```

示例 ID、文本与矩形仅说明字段；实际提交必须读取源文件。links 引用本次清单中其他卡片 ID，不允许悬空或自指。figure 必须对应同一页的证据，rect 为 PyMuPDF 页面显示坐标、单位 point；必须先查看裁剪是否正确。服务从冻结 PDF 生成真实 PNG，存储哈希、原始页码和裁剪矩形，不接受另画的图充当原论文系统图。

`app/kw.cmd jobs ingest` 先验证产物与事实证据。`app/kw.cmd knowledge-bases assemble <库ID> --job <任务ID> --if-revision <库revision>` 再验证卡片和图像、关联到层级并发布。只有 ready 索引、匹配的库版本、当前成员和资源版本能够组装。服务校验来源可追溯性，语义卡片标记为 Codex 整理、待审核。

`app/kw.cmd knowledge-bases cards <库ID>` 读取卡片。可视化知识库的“知识卡片”页按层展示文字、图片、关联与来源按钮。`workspace/knowledge/<库ID>.json` 发布同一内容，窗口关闭后 Codex 也能读取。重建索引或改变资料使旧卡片失效，图片接口也随之拒绝读取旧卡片；历史文件保留便于追溯。

新建任务的 v4 方法、主张级证据、多层归属、双路检索与方案验收见 [RESEARCH_V4.md](RESEARCH_V4.md) 和内置知识构建技能；上面的字段只描述兼容基础格式，不能替代新冻结任务的完整合同。
