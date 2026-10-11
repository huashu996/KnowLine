---
name: knowline-word-citations
description: 使用知序领域内核验论文为项目 Word 工作副本插入动态引用，生成参考文献、自动重排，并统一引用样式与文献字体格式。
---

# 知序 Word 引用

先读 [Word 协作工具说明](../../docs/WORD_CITATIONS.md)。本工具使用独立工作副本；普通样式使用 Word 原生引用域，数字上标使用 Word 富文本内容控件、书签和双向内部链接，不是 EndNote CWYW 插件。数字上标的文末文献为普通段落，保持连接时删除文末文献段落或正文引用会双向同步并重排编号。

按领域读取论文正文与 `app/kw.cmd word sources --domain "名称"`。缺失作者、年份、刊会、来源类型或 verified 状态时，核验原始发布来源后用带 revision 的 resources update 提交；不能从文件名猜元数据。按段落具体含义选论文，不把整组引文无差别堆在段落末。

用 `word open --document <项目内DOCX>` 创建副本；已有会话按文档路径区分，不默认第一项。`word inspect --session <ID>` 获取段落或选区 text_hash。cite 携带同一 hash、领域名和明确资源 ID，多篇使用重复 --resource。文本过期重读；同一操作 ID 重试参数保持一致。

按用户要求生成 bibliography、选择本机可用 IEEE/APA/GB7714 样式，并通过 format 统一参考文献字体、字号与行距。连接期间正文删除或移动引用会自动重排。删除领域成员不等于删除文档证据；工作副本已有来源独立归档。

保存到 outputs/word，检查正文引用、参考文献顺序、重复引用一致性、未用文献移除以及格式。只检查本次工作副本，不修改用户原文件或既有 Word 实例。不声称本机样式符合最新国标或某期刊全部要求；需要时按用户模板核对。

自动桥执行时，以任务提示中的自动回流规则为准：写 result.json 后退出，由知序执行 claim/ingest 与校验，不自行重复领取或提交。接入协议见 app/docs/LOCAL_AGENT.md。
