# 引用记录与 PDF 独立获取

本项源码与隔离测试已完成，状态为 `SOURCE_READY_FOR_FINAL_REPACK`。本聊天不安装程序、改启动器或清空资料。统一封装由聊天“知序支持代码项目与源文件导入”（`01a11b76-fa76-73e3-ab6f-cad01b8af3a2`）负责。最终源码摘要在 `citation-source-manifest.json`；须以该摘要核对最终包，不能把此前候选 EXE 的验收当成本项最终补丁已经部署。

## 行为与操作

引用是独立的 `paper_records`，不要求先取得 PDF 或学校订阅。正式出版记录使用核实的正式 DOI、最终题名、作者、刊会、年份及可得卷期页码。PDF 分别保存实际身份、版本、来源依据、获取方法、获取时间与失败/暂停原因。作者接受稿、旧预印本 PDF 可以关联正式引用，但须有来源声明的同篇标识关系及作者一致性证据，不能只按相似题名合并。

“查找新论文”中的“引用记录”可先核验 DOI 或 arXiv 编号，再单独获取 PDF。“刷新并导出引用”在导出前请求当前来源；来源不可用时保留已保存记录并明确报错，不将旧记录冒称刚核实的最新版。

在 Knowline 项目目录通过原 CLI 使用：

```powershell
app/kw.cmd citations list
app/kw.cmd citations resolve --doi 10.1371/journal.pmed.0020124 --consent
app/kw.cmd citations resolve --arxiv 1706.03762v1 --consent
app/kw.cmd citations export <记录ID> --consent --format ris
```

人工操作还须开启本实例的联网设置。已获用户授权的研究任务使用 `--job <任务ID>`，沿用冻结范围，不要求额外全局联网授权。可用 `--domain <领域ID>` 关联领域；关联已有 PDF 用 `--resource <资源ID> --pdf-identity <实际PDF身份JSON路径>`。关联失败时引用保留，PDF 文件和标注也保留，返回 `pdf_link.status=needs_user` 及具体原因。

自动获取清单和任务 `imported_papers` 写 `citation_record_id`。PDF 失败仍写实际 `unavailable_reason`；仅引用成功为部分完成，不计作全文成功。PDF 成功而元数据不足时保留 PDF，状态不伪装为完整核验。正式 OA 使用公开访问方式；无学校订阅权限不能挡住合法公开 OA。登录、过期、未知官方站点及验证挑战仍按原受控浏览器规则处理。

arXiv 查询去掉用户输入的 `vN`，向仓库查询当前版本。没有可核实正式记录时只保存核实的当前预印本，明确“正式出版未核实”；该状态不意味着论文从未正式发表。保留首次发布与当前版本提交日期；预印本 `year` 表示当前版本提交年份，不冒充正式出版年份。Crossref 当前 DOI 元数据与仓库声明的 DOI/版本关系用于正式升级；不会通过近似题名猜测关系。

## 数据与安全

仅增加引用表，不全库搬迁或替换已有文件。原资源 ID、版本、哈希、路径、标注、领域与知识库成员、冻结任务引用保持原合同。旧引用 ID 升级后保留为明确别名，查询和 Word 来源选择读取其当前正式记录。引用独立刷新不改未变知识库快照；事件序列和原子发布检查保留。已提交发布中断由原恢复机制恢复。

引用来源只请求固定公共元数据 API，不读取认证 DOM、Cookie、令牌、密码或日常浏览器 Profile。保留有界、脱敏的书目及跨版本身份依据。元数据请求最多 2 并发，Crossref 请求起始间隔至少 1 秒，arXiv 至少 3 秒；单请求 15 秒、响应 2 MiB，关闭代理环境继承和自动重定向。PDF 认证和下载仍使用既有受保护 WebView2 Profile、批准主机与代理路径。

## 可复查验收

测试资料全部隔离，未以真实知识库做压力测试，未运行模型研究任务。

| 证据 | 实测结果及边界 |
| --- | --- |
| `citation-pdf-separation.json` | 18 场景通过；真实 API/单写数据库/PDF 解析、导入与 Word 来源 XML；元数据接口和认证结果为模拟。覆盖正式引用无 PDF、预印本到正式升级、v1 请求解析当前 v3、旧版拒绝、旧 ID 更新、RIS 卷期页码、429 不导出旧记录、PDF 关联冲突互不丢失、未变快照不改、合法替代回退、原文件与批注保留、重启/发布中断恢复。 |
| `citation-regressions.json` | 机构访问 17 项、多站点 5 组、获取桥接 8 组、资源合同、代码导入及方案来源兼容测试通过。知识库单独选择、论文单独选择、代码单独选择均可生成方案输入，不重新要求选论文/代码。 |
| `citation-native.json` | 4 项真实 WebView2 浏览器回归通过：模拟订阅、公开 OA、正式页面定位、独立会话未继承认证。服务器、认证和 PDF 为本地测试数据，不证明任何真实学校订阅。 |
| `citation-public-metadata.json` | 真实 Crossref 请求通过：`10.1371/journal.pmed.0020124` 返回正式题名、作者、2005 年、PLoS Medicine、2(8)、e124；未下载此论文或测试学校认证。 |
| `citation-public-arxiv.json` | 真实 arXiv 请求通过：输入 `1706.03762v1`，仓库返回当前 v7、首次 2017-06-12、v7 提交 2023-08-02。未建立可核实正式 DOI 关联，记录明确标记正式出版未核实，而非宣称未发表。 |

界面源码已完成构建验证；本项最终补丁尚未由本聊天验收安装后的完整 UI，不以构建通过宣称交互性能改善。此前多站点界面截图属于其相应历史验收，不作为本项引用界面的新截图。统一交付报告另行记录最终包及实际桌面状态。

## 修改文件

- 新增 `backend/paper_bibliography.py`：固定公开源解析、当前版本核验、独立引用、别名和身份桥接、导出、独立 PDF 状态。
- `backend/store.py`、`project_catalog.py`：增量表、目录发布、可接收独立引用/PDF 身份字段、关系图导入分别核验两类成果。
- `backend/app.py`、`cli.py`：引用列表/核验/导出入口，PDF 关联失败不回滚引用，任务联网与冻结范围校验。
- `backend/acquisition_metadata.py`、`institutional_access.py`、`institutional_broker.py`：引用字段优先、PDF 身份与版本独立、显式跨版本关系、公开 OA 与合法替代、暂停/失败分别记录。
- `backend/literature_results.py`、`research_fast.py`、`codex_runner.py`：引用与全文分别计数、元数据刷新优先于旧缓存、独立成功/缺项的任务指令与验收。
- `backend/word_sources.py`、`word_references.py`：正式引用与 PDF 元数据分离、仅元数据来源、预印本标记与旧 ID 升级查询。
- `frontend/src/App.tsx`、`CitationRecords.tsx`、`citation-records.css`、`PdfProvenance.tsx`：引用管理与双语状态展示；引用事件仅通知相关组件，不触发全资料刷新。
- `research-skills/knowline-import-papers/SKILL.md`：移除引用必须来自取得的 PDF 页面、零 PDF 必判失败等冲突规则。
- `tests/citation-pdf-separation.py`：本项隔离回归。`tests/packed_runtime.py` 的资源读取修复由统一封装聊天提供，保证源测试可读取本安装 certifi CA 文件，未关闭 TLS 校验。
- 本说明、`READER_PROPOSAL_METADATA.md`、`WORD_CITATIONS.md` 的相应操作补充，以及本目录上述 JSON 验收证据。

## 剩余限制

没有合法学校测试账号，真实学校登录/订阅、IEEE 指定文章的正式 PDF 权限仍须用户自行认证并逐篇实测。认证页停在加载状态不计作登录成功；书目可读也不证明 PDF 权限。

当前版本适配覆盖 Crossref 当前 DOI 与 arXiv 当前版本及明确关系；不宣称查尽所有出版社或预印本仓库。其他仓库的 posted-content DOI 单独不能证明最新版本，明确拒绝冒称最新。作者缩写/顺序变化、缺标识的扫描 PDF、含歧义的关系需人工核验；不以标题相似放宽身份检查。

旧资源不做批量迁移，未关联独立记录的旧书目沿用原合同，应通过显式核验升级。新建 Word 来源要求受管理记录最近 5 分钟内核验；CLI 引用导出每次重新请求来源。已经写入 DOCX 的冻结书目继续保留，现有 Word 刷新只刷新编号/样式，不自动将所有历史引文元数据升级；此项未增加全篇来源同步。已有人工锁定字段、PDF 版本标注不会静默覆盖。

本聊天交付范围为最终源码、测试与共享报告；最终 EXE 是否包含此处源码以统一封装聊天的最终模块核验为准。
