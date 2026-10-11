# 机构访问 / Institutional Access

2026-10-08 更新为多网站独立会话，沿用既有 Knowline 桌面、检索任务和单写导入服务。当前操作及本次验收见 [多网站更新说明](INSTITUTIONAL_SITES.md)。下方历史验收记录保留其当时的运行版本。

## 使用

1. 打开“设置 → 机构访问”，填写学校、出版社或数据库的官方 HTTPS 登录入口并点击“添加网站”，然后点击对应卡片的“连接”。名称可选；添加表示确认官方入口，不表示学校身份或订阅权限已核实。
2. 在此网站的专用 WebView2 窗口自行输入账号、密码和验证码，完成后点击“登录完成”。新增网站使用另一个独立受保护 Profile，不覆盖原 IEEE 登录。高级设置和诊断与手动导入区已从设置页面完整移除。
3. 实际认证遇到未知主导航时先阻止访问，窗口只显示主机名和“确认当前显示的官方站点”。仅在学校/出版方确认它为官方服务时批准；批准后继续同一受控窗口，不退出或清除登录。原始认证 URL 只保留在窗口内存，状态中仅保存主机及确认 ID。任务首次需要新出版方时也会暂停并在设置提供确认；确认后重试原任务。私网/本地目标和非 HTTPS 不能批准，不自动放开任意站点。
4. 点击“登录完成”后认证窗口隐藏。继续使用原有论文检索、候选获取与关系图全文导入；已配置机构的任务说明会调用公共服务的受控会话接口，自动按清单串行获取并导入冻结领域或资料库。无需用户逐篇填写诊断表。仅初次认证、过期、权限/挑战需要人工处理时显示窗口。点击“连接”可以再次显示现有窗口。
5. 已配置的学校显示名、访问路线、代理模板和已确认的特定 DNS 映射例外继续生效，后台配置与安全校验保留。新官方主机按实际访问需要确认。新的特殊代理如无法可靠映射，须暂停自动获取，合法手动下载后从普通资料区导入；软件不猜测代理路径或修改 VPN。
6. 任务在对应网站的会话中核验论文 PDF 并沿用现有导入流程。卡片分别显示用户登录报告、会话可供任务检查的状态和最近单篇 PDF 核验的站点/时间；登录不等于全部订阅。资料区保留手动导入，设置不再显示单篇诊断表。
7. 正式版无法取得时，明确填写原因，再选择合法接受稿、预印本或未知版本。版本依据属于用户依据来源作出的确认，软件的身份匹配不会自动证明版本；书目类型 JournalArticle 也不会证明版本。
8. 禁止自动获取、学校不支持嵌入认证或需要人工获取时，合法手动下载后使用普通资料区导入。后台原有带论文身份核验的手动接口继续保留，但设置不再提供其入口；普通文件导入不会将机构会话或出版版本自动标为已验证。
9. 同一 DOI/访问地址至多 2 次，间隔至少 5 秒，单个 PDF 128 MiB，每个实例一次一篇。人工测试 300 秒；自动获取每来源最多 120 秒、书目请求 60 秒，每候选最多 3 来源、CLI 每批最多 10 条；仅处理冻结任务清单和数量，不生成无清单抓取。取消后可重试；挑战/权限需人工在窗口处理并点击“登录完成”，不会自动重试绕过。
10. 各网站分别提供“连接”“重新登录”和“退出此网站”。重新登录/退出只清除该网站会话，保留入口及其他网站登录；任务使用中的会话不允许清除。文件仍锁定时明确提示清除未完成，稍后重试，不声称退出已完成。已导入论文不受影响。

## 会话及实现

检查了 desktop_entry.py、codex_runner.py、research_fast.py、literature_results.py、设置页面、导入接口和现有 pywebview 6.2.1/WebView2 运行库。原桌面窗口虽然有 WebView2 下载能力，其用户目录属于主工作台；codex exec 和 urllib 都不能复用浏览器认证。

本功能在独立进程中直接使用现有 WebView2 WinForms 控件。用户认证、页面访问和下载使用同一个 CoreWebView2/Profile。附件通过 DownloadStarting/DownloadOperation；内嵌 PDF 在原始网络响应阶段通过官方原生协议 Fetch.takeResponseBodyAsStream/IO.read 读取，避免 PDF 查看器返回 HTML 外壳。没有另发 urllib 认证请求，没有读取或导出 CookieManager，没有网页到本地的 JS/Python 桥。自动任务只执行固定本地脚本：先以布尔值检测密码框/挑战，再提取 citation_title/doi/author/pdf_url 和有限论文链接；认证输入值、原始 HTML、任意脚本均不提供模型或 API。

`InstitutionalBroker` 是设置与所有论文任务的共用通道。discover_papers / import_graph_papers 通过 acquire 获取，paper_relationships 只允许 lookup 获取书目。后台请求复用同一受保护 Profile，关闭窗口后可隐藏恢复；冻结候选 ID、题名、已有 DOI、年份、数量、目标领域和联网许可受检查。warm 缓存中缺失全文且已配置机构时进入实际获取流程，不能沿用“公开 URL 不可用”直接跳过订阅。接口返回资源 ID/版本/哈希及脱敏获取证据；不返回任何会话材料。版本依据分别标明用户确认或任务来源证据，PDF 身份核验不是出版版本认证。

会话保存在当前 Windows 用户的 LocalAppData/Knowline/InstitutionalAccess 下，以绝对安装路径和 OS 用户身份分别隔离；目录移除继承 ACL，仅当前用户及 SYSTEM 可访问。浏览器自行管理 Cookie 的受保护存储，关闭密码自动保存和表单自动填充。认证页面内容、完整跳转地址、敏感请求头及 Cookie/令牌不写入模型、项目、操作日志或 Git。工作进程标准输出/错误被丢弃，调试窗口关闭。修改本机 VPN、代理、证书、系统浏览器配置均不属于本功能。

状态为 unconfigured、awaiting_login、awaiting_test、verified、expired。登录完成是用户报告；验证必须有实际身份匹配 PDF。验证记录限定一篇 DOI、站点、访问方法和时间；超过 12 小时要求重新测试。OA 验证记录 public_publisher，不证明学校订阅。401 标记过期；403/429、已识别挑战响应暂停；无法可靠识别的验证码/其他挑战由用户在窗口点击“验证挑战：暂停”。不会自动解决验证码。

限制主导航、子框架、弹窗、资源请求和下载目的地主机；HTTP、文件、localhost、私网地址及未批准主机被拒绝。第三方广告子框架被拒绝，主跳转越界则停止并只显示主机名。应用接口继续使用原有令牌、Host/Origin 校验，额外拒绝跨站 Fetch。URL 只允许 HTTPS、无用户名密码、无片段和明确列举的稳定参数（包括 DOI、IEEE arnumber、搜索词以及校验后的嵌套代理 url）；临时签名 PDF URL 仅留在浏览器内存/受保护浏览器存储，不进入清单或元数据。

## 任务接口（服务内部 / CLI）

`app/kw.cmd institutional status` 仅返回状态、已批准主机与该站点测试时间。`app/kw.cmd institutional lookup --job <本任务ID> --url <批准的稳定检索或论文页面>` 返回最多 20 条书目/候选链接及 `metadata_only_not_pdf_entitlement`；无适配字段时返回 `no_supported_bibliographic_markup`，不能算检索完成。IEEE / Web of Science 的书目可读与对应出版方全文订阅是不同结论，单独记录站点和时间。

`app/kw.cmd institutional acquire --job <本任务ID> --manifest <本任务清单JSON>` 使用下列结构（所有事实须按原始来源核验；年份在冻结范围内；最多三来源）：

```json
{"papers":[{"candidate_id":"冻结候选ID","doi":"10.1234/example","title":"Full article title","authors":["Ada Example"],"year":2020,"venue":"Journal",
"sources":[{"publisher_url":"https://publisher.example.edu/article","access_url":"https://publisher.example.edu/paper.pdf","public_oa":true,"download_permitted":true,"pdf_version":"published","version_basis":"Publisher explicitly identifies the version of record"}]}]}
```

优先正式 OA，再机构正式版，最后合法替代（增加 `fallback_reason`、`version_source_url` 和 accepted_manuscript/preprint/unknown 分类）。原始出版方页与替代版依据来源分别保存。成功返回 `imported` 和真实 resource_id/version_id/sha256/acquisition，直接接入原任务 registration-log / imported_papers；已有相同哈希标注保留。`needs_user` 暂停相关机构步骤，`unavailable` 明确记缺项或选合法替代。公共服务保持原有单写事务，CLI/模型从不获得机构 Cookie。任务结果仍由现有验收流程审核，不因接口返回而跳过验收。

某些用户已连接的网络采用 198.18.0.0/15 DNS 映射。本机验收网络属于这种情况。默认拒绝该非公网范围；仅在用户勾选确认后，对已批准主机允许这一特定映射范围，继续拒绝 localhost、其他私网和任意端口。此选项不安装或修改网络。未确认网络用途时保持关闭。

下载直接进入 resource/incoming 的 .kw 暂存文件，自动扫描忽略暂存。导入前重复解析和匹配，并核对下载哈希；之后使用原有 filename 命名、import_local 哈希去重、不可变证据版本和领域关联，不直接写 catalog/SQLite。新元数据保留 publisher_url、access_method、pdf_version、pdf_version_basis、acquired_at、fallback_reason。已有相同哈希论文的人工版本/元数据/批注不被覆盖；不同字节的正式版与替代版可以并存。

## 验收证据

| 验收 | 结果 | 证据 |
|---|---|---|
| 两个学校入口、代理路径、用户及安装路径隔离、状态、重试限额、版本与回退、PDF/身份、手动路径及 API 边界 | 原 15 项回归保留；学校使用 Alpha/Beta 模拟入口；最新总数见下行 | verification/institutional-access.json |
| 单网址首次连接、同入口再次连接保留高级路线、批准主机与会话标记、域名确认拒绝过期 ID 和不安全网络、退出清除 | 最新逻辑/API 共 17 项通过（原 15 项及新增 2 项） | verification/institutional-access.json |
| 未知认证主机暂停、确认后同一窗口继续认证且 Cookie 保留、连续任务获取 | 2 项真实 WebView2/模拟服务通过；无真实账号 | verification/institutional-simple-native.json |
| 原生 WebView2 同会话订阅/OA、内嵌 PDF、403/401/429、200 挑战、伪 PDF、隔离、取消重试、页面定位、书目和登录页检测 | 14 项实际浏览器测试通过；账号/订阅服务为模拟 | verification/institutional-native.json |
| 隐藏原生浏览器认证后连续两个自动请求复用会话 | 实际 WebView2、模拟订阅通过 | verification/institutional-native-consecutive.json |
| 自动检索任务导入、冻结图候选导入、会话复用、重复标注保留、书目权限分离、过期/权限/挑战暂停、版本回退、数量及接口边界 | 7 组测试通过；真实 API/PDF/单写导入，模拟浏览器结果 | verification/institutional-broker.json |
| 正式 OA 下载、真实 PDF、身份、哈希、自动任务后台导入 | 发布包实测 PLOS Medicine，10.1371/journal.pmed.0020124；原论文页面自动定位及导入通过 | verification/institutional-oa.json |
| 已有 PDF 替换、稳定资源 ID/领域/旧版本/哈希和 revision 冲突 | 既有回归测试通过 | verification/pdf-replacement.json |
| 默认仅一个网址输入、高级/诊断折叠、连接请求无技术必填、已有高级配置、中英文及窄屏、离线与待确认状态 | 通过；UI 模拟窗口创建，原生会话另由浏览器测试覆盖 | verification/institutional-ui.json |
| 运行包新增模块及入口、其余模块保留 | 归档逐模块核验通过 | verification/institutional-package.json |
| 本实例服务部署、资源 ID/版本/哈希保持、任务空闲检查 | 已通过；端口 21867，当前运行 Knowline.exe | verification/institutional-deployment.json |

正式 OA 样本的出版方来源：[PLOS 原始论文页面](https://journals.plos.org/plosmedicine/article?id=10.1371/journal.pmed.0020124)。原生方案参考 [WebView2 用户目录](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder)、[WebView2 下载事件](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2downloadstartingeventargs?view=webview2-1.0.2849.39) 和 [官方浏览器原生 Fetch 协议](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)。

## 未实测与限制

原初次机构功能验收没有合法学校账号，历史报告的学校/订阅认证为模拟。当前原实例已有用户自行认证后获得的 IEEE 单篇 PDF 验证记录，多网站更新已保留该记录和会话；本次没有新增网站账号或再次认证测试。学校名单不构成兼容声明，其他真实机构/站点须由用户自行认证后逐篇验证。IEEE 正式页/PDF 与 WoS 书目请求已提供受控同会话通道，但未提供已实测的 WoS 动态表单/API 检索适配，不能宣称所有平台自动检索完成。特殊动态站点只能返回可识别书目，否则明确缺项。历史发布包已从 PLOS 原论文页自动定位并取得正式 PDF、核对身份及导入；其他真实出版社页面自动定位须分别验证。

嵌入浏览器可能被某些身份提供方禁止；不改证书、不绕过认证，应人工下载导入。内部私网学校入口、自定义代理协议、含不支持查询参数的入口、需要多个并列弹窗的认证尚未支持。未知官方主导航按需确认且保留同一会话；SAML 等被阻止的 POST 跳转可能需批准后返回官方入口再继续，不复制或重放密码与 POST 内容。扫描件、无 DOI、跨页拆散/缺失 DOI 或作者字形不一致可能无法严格匹配，须走已有人工核验流程，不能自动标为验证通过。版本分类依赖用户提供的来源依据，不是自动出版认证。Windows 相同 OS 账号中的多人共用同一安装不是独立账户；应使用独立 OS 账户或独立安装路径。搬动安装路径会创建新会话，原位置的会话需在原安装退出清除。

## 修改文件

- backend/institutional_access.py：配置、隔离、安全地址、PDF 身份验证、手动文件路径、现有单写导入。
- backend/institutional_browser.py：专用原生 WebView2 窗口、下载事件和内嵌 PDF 流、安全边界与暂停。
- backend/institutional_broker.py、cli.py：全局任务通道、隐藏复用、自动获取/导入、受控书目请求、冻结范围和数量限制。
- backend/app.py、store.py：接口、跨站拒绝、获取元数据、暂存排除及既有导入支持。
- backend/codex_runner.py、research_fast.py、literature_results.py：明确无登录态共享、来源脱敏、版本结果检查。
- desktop_entry.py：独立机构工作进程入口。
- frontend/src/InstitutionalAccess.tsx、institutional-access.css、PdfProvenance.tsx、App.tsx、api.ts：双语设置、单篇/手动入口、获取版本展示。
- frontend/vite.config.mjs：支持隔离构建依赖目录，保留原有默认构建方式。
- tests/institutional-access.py、institutional-native.py、institutional-broker.py、institutional-oa.py、institutional-ui.mjs、packed_runtime.py：隔离验收。
- scripts/package_institutional.py：只替换已修改归档模块，不重建产品或复制研究资料。
- scripts/deploy_institutional.ps1：检查实例身份、空闲任务、验证报告与包哈希，仅重启本实例服务并更新入口。
- docs/INSTITUTIONAL_ACCESS.md、research-skills/knowline-import-papers/SKILL.md：操作与获取合同。
- Knowline/Knowline.exe 及 Knowline/_internal/dist：最终运行入口与界面；项目根 StartKnowline.cmd、app/StartServer.cmd、app/kw.cmd 已更新。原有窗口锁定旧入口时保留它，只重启本实例服务；不关闭其他窗口。重新打开/刷新知序可加载新界面。

默认界面效果见 verification/institutional-ui-zh.png（模拟配置），另提供 en/narrow 截图。2026-10-07 本次变更：InstitutionalAccess.tsx/CSS 单网址默认视图及折叠排障；institutional_access.py/app.py 缺省配置和同入口兼容；institutional_browser.py 窗口就地主机确认；institutional_broker.py 按需站点交接；相关测试、打包与部署脚本。原配置和受保护会话目录在本次部署保留，退出仍可清除。
