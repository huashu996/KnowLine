# Codex 项目与 Word 动态引用

引用操作由当前 Codex 执行，不需要模型 API。知序保存领域和已核验论文；普通样式使用 Word 原生 `CITATION`、`BIBLIOGRAPHY` 域，数字上标样式使用 Word 原生富文本内容控件、书签和内部超链接，并在 DOCX 中保存来源身份及元数据。使用本机 Windows 桌面 Word，不能用 WPS 或纯网页 Word 代替。

## 使用流程

引用元数据与 PDF 版本独立。已关联独立引用记录的资源优先使用当前核验的正式书目，领域也可提供仅元数据引用；新建受管理来源要求最近五分钟内核验。先用 `app/kw.cmd citations resolve` 或 `citations export` 更新来源；获取旧预印本 PDF 不改变正式 DOI/年份。已有 DOCX 冻结书目不自动全篇升级，详见 [引用与 PDF 分离](CITATION_PDF_SEPARATION.md)。

用户可以对 Codex 说：“打开这个项目的论文草稿，给第三段引用世界模型领域里相关的论文，统一成 IEEE 格式。”Codex 按含义核对来源，不把整个领域所有论文机械插入同一段。文字和 Codex 语音使用相同工具。

1. 先在桌面版 Word 中打开并保存目标 DOCX。点击领域论文的“引用”，从已打开文档列表选择原文档并连接。文档可在项目外；引用直接写入所选原文档，不创建工作副本。多个 Word 实例按具体文档定位。
2. 读取领域的论文、真实原文和元数据。作者、年份、刊会、来源类型必须完整且已核验；缺失时先补元数据及其证据。
3. 读取 Word 段落或当前选区，保存文本校验值，再插入所选论文的原生引用域。
4. 新连接的无引用文档默认使用数字上标，首次引用会自动在文末创建动态参考文献表。设置页可选择“数字上标（顺序编号）”、普通 IEEE、APA 或本机 GB7714，并统一字体字号、刷新和保存。已有引用文档保留原样式，按需要显式切换。
5. 连接期间，Word 修改引用后约一秒刷新：IEEE 按首次出现顺序编号，同一论文复用号码；APA 按作者年份显示，参考文献按作者排序。完全删除某篇的正文引用后，其条目从参考文献表移除。
6. 数字上标样式的文末文献使用普通段落，不生成表格。正文编号链接到文末对应条目，文末编号链接回首次引用位置，按 Word 当前设置使用 Ctrl+单击跟随链接。连接期间，删除文末某篇完整文献段落，会同步从所有正文引用组中移除该文献，并重新编号；删除正文引用也会更新文末列表。

## 项目工具

```powershell
app/kw.cmd word sources --domain "世界模型"
app/kw.cmd word open --document "incoming/草稿.docx"
app/kw.cmd word sessions
app/kw.cmd word inspect --session <session_id>
app/kw.cmd word cite --session <session_id> --domain "世界模型" --resource <paper_id> --paragraph 3 --if-text-hash <paragraph_text_hash> --operation-id <unique_id>
app/kw.cmd word cite --session <session_id> --domain "世界模型" --resource <paper_a> --resource <paper_b> --selection --if-text-hash <selection_text_hash>
app/kw.cmd word bibliography --session <session_id>
app/kw.cmd word style --session <session_id> --name IEEE
app/kw.cmd word style --session <session_id> --name IEEE_SUPERSCRIPT
app/kw.cmd word style --session <session_id> --name APA
app/kw.cmd word format --session <session_id> --font "Times New Roman" --size 10.5 --spacing 1
app/kw.cmd word save --session <session_id>
app/kw.cmd word close --session <session_id>
```

段落校验值由 `inspect.paragraphs[].text_hash` 提供；选区校验值由 `inspect.selection.text_hash` 提供。选区必须在目标文档正文，工具在选区末尾追加引用，保留原文。内容变化后旧校验值会拒绝写入。显式 `operation_id` 用于超时重试，不重复插入；不能复用于不同参数。

现有论文核验后可通过同一个资料写入工具补元数据：

```powershell
app/kw.cmd resources update <paper_id> --metadata "incoming/paper.metadata.json" --if-revision <revision>
```

元数据包含 `title`、`year`、`venue`、`authors` 数组、`source_type`、`metadata_status="verified"` 及真实 `field_sources`。作者最好使用 `{ "family": "姓", "given": "名" }`。`source_type` 支持 `JournalArticle`、`ConferenceProceedings`、`Report`、`Book`；不根据文件名猜测论文的出版类型。DOI、卷、期、页码、URL 可补充，但不得编造。

## 保存、保护与边界

- 每个会话拥有独立 Word 实例和唯一工作副本。工具不绑定用户已经打开的 Word 实例，不修改全局来源库或 Normal 模板；退出只关闭自己的目标文档。如果有人在该实例打开其他文档，保留该实例。
- 来源记录保存资料 ID、版本 ID 和哈希。来源随 DOCX 保存，重新打开仍可切换样式。已删除的知序引用来源保留在专用自定义 XML 存档；恢复其引用时可以找回来源。
- 首次引用时冻结来源元数据；之后的平台元数据变更不自动覆盖 Word 的来源记录。资料版本发生变化时拒绝静默替换，显式来源同步尚待增加。
- 软件领域的成员调整不会静默删除 Word 中已有引文。正文引用代表文档证据，删除领域与删除正文引文是不同操作。
- 自动刷新只在协作会话运行时有效。关闭会话后，数字上标的段落、来源身份和双向跳转仍保留在 DOCX 中，增删自动同步需要重新连接知序；普通样式仍可通过 Word 更新原生域。自动刷新不会自动保存用户正文；使用“保存工作副本”或 Word 保存。
- 目前只支持正文引用。表格、页眉、脚注内的引用位置会拒绝自动写入；开启修订或尚有修订的文档也会拒绝更新，不擅自接受/拒绝修订。
- 不混用 EndNote/Zotero/Mendeley 的引用域，不转换其现有引用为静态文字。此版本是项目协作工具，没有安装 Word 功能区插件。
- IEEE、APA、GB7714 使用本机 Word 样式定义。版本取决于本机安装，例如这里的 APA 为第六版；不声称内置 GB7714 等同于最新 GB/T 7714 或某个期刊的全部规范。
- 输入 DOCX 的宏、OLE/ActiveX、自动外部加载内容和 DDE 等活动域会在 Word 打开前拒绝。普通超链接保留，不自动访问。

## 自测

`scripts/test_word_live.py` 在真实 Word 16.0 中创建独立合成测试文档，通过 Codex 使用的同一套 CLI 操作。覆盖重复引用、重试、单项及整项删除、移动段落、合并引用、IEEE/APA/本机 GB7714 样式、字体字号、修订保护、保存重开、原件校验及另一个 Word 实例不变。报告位于 `tests/reports/word-live/results.json`；测试来源明确标为 synthetic fixture，不能用于正式论文。

依据：[Microsoft Word 引用与书目对象模型](https://learn.microsoft.com/en-us/office/vba/word/concepts/working-with-word/working-with-bibliographies)、[Source.Delete](https://learn.microsoft.com/en-us/office/vba/api/word.source.delete)。

断开连接只刷新并保存所选原文档，不关闭用户文档或 Word，不另外保存 DOCX 副本。已有 EndNote、Zotero、Mendeley 动态引文的文档仍需使用对应引用工具，避免混用。
