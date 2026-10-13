# 多网站机构访问更新 · 2026-10-08

本次在原实例上增量更新，没有重建软件、迁移知识库或复制认证资料。运行入口为 `app/Knowline/Knowline.exe`，端口仍为 21867。三个原启动脚本已更新。

## 使用

在设置的“机构访问”中，现有入口以网站卡片显示。填写另一网站的官方 HTTPS 登录入口，可选名称，点击“添加网站”，再点击该卡片的“连接”。输入的网址须由用户确认为学校或出版方的官方服务；未指定的新网站不会由软件猜测。账号、密码和验证码仅由用户在专用窗口输入。

每张卡片分别连接、重新登录和退出。重新登录/退出只清除该网站的浏览器会话，保留入口及其他网站会话。重复添加同主机不会覆盖既有配置。若某学校入口用于多个出版方，应在实际跳转时逐一确认官方主机；存在多个匹配会话时任务暂停，要求明确选择。

“高级设置”和“诊断与手动导入”区及其展开入口完整移除，保留简洁的网站列表、添加、会话按钮、状态与必要的官方站点确认。后台访问路线、安全校验、受控手动接口和普通资料区导入保留。

## 会话和权限

- 原 IEEE Profile、配置和单篇 PDF 核验记录留在原位置。新网站使用兄弟目录内独立的受控 WebView2 Profile，另有只保存随机网站 ID/名称的受保护注册表。不复制 Cookie，不读取日常浏览器认证资料。
- 用户点击“登录完成”仅记录报告时间；“会话可供任务检查使用”表示可尝试对应任务。实际 PDF 验证单独记录站点、论文及时间，不承诺所有出版社、期刊或文章可访问。
- 已关闭窗口保留会话，由任务在同一 Profile 隐藏恢复后重新检查。新网站未登录/过期/挑战/权限不足会暂停对应步骤，不能继承 IEEE 的验证结论。
- 下载和书目请求根据出版方主机、明确网站 ID 或唯一匹配代理选择会话。等待结果、取消和导入固定绑定该会话；新增或连接另一网站不改正在下载网站的命令、目标或暂存文件。并发、频率和重试限制仍跨网站统一控制。
- 既有单入口配置/连接 API 保留。向旧连接 API 提交不同主机现在新增独立入口，不清除原入口；同主机复用原会话。`institutional lookup` 支持可选 `--site`，acquire 清单的来源可含 `site_id`。未知官方主机确认仍限定目标会话。
- 真实 PDF 解析、DOI/题名/作者匹配、来源脱敏、版本分类、哈希去重、原子发布和单写导入沿用原合同；已有人工标签与标注不因替代版或重复文件而覆盖。

## 本次验收

| 验收内容 | 结果与可复查文件 |
|---|---|
| 新增/重复/重启、A 下载时新增/连接 B、B 单独退出/重新登录、主机路由、独立过期、真实 PDF 解析与单写导入 | 5 组通过，`verification/institutional-multisite.json`；浏览器结果和学校均模拟 |
| 原配置、两所模拟学校、PDF/身份/版本、API 及安全边界 | 原 17 项通过，`verification/institutional-access.json` |
| 原任务冻结范围、获取导入、重复标注、书目权限分离、挑战/过期/权限和回退 | 原 7 组通过，`verification/institutional-broker.json`；认证结果模拟 |
| 原生 WebView2 同会话订阅、内嵌 PDF、不同 Profile 隔离、连续请求、新官方站点确认 | 5 项通过，`verification/institutional-sites-native.json`；真实浏览器、本地模拟认证服务，无学校账号 |
| 实际 React 页面和 API：新增/登录报告/退出/重复、旧单入口 API、官方确认、请求边界、完整移除两区、中英文及窄屏 | 7 组通过，无页面脚本错误，`verification/institutional-sites-ui.json`；窗口登录/DNS 显式模拟 |
| 已有代码导入行为 | Python/C++/TSX/Java/Go/Rust、空源码、项目层级、去重、PDF 与知识索引回归通过，`verification/code-import-api.json` |
| 运行包/源码 | 后端全部模块和桌面入口逐模块一致，未改依赖模块字节保留，`verification/sites-package.json`、`verification/optimization-runtime-sites.json` |
| 实例更新 | `verification/sites-deployment.json`：原 IEEE Profile 保持原位，配置与单篇核验记录保留；切换前后资料、知识库、分组、任务、关系、想法 API 的合并 SHA256 都为 `31b5b49b077eeab7e68c321b258e53aa1c27a1abab62980beec4a977e0b66f10` |
| 实际发布页面 | `verification/institutional-sites-live.json`：新界面、旧 IEEE 核验记录、两区完整移除、无页面错误均通过；未发起新的真实登录 |

当前包 SHA256：`553d11b4187aed32021790b30e4ee6676cd004d61ae994f8c6087a983e550efc`。初次切换关闭本实例拥有的一个专用浏览器工作进程并保留 Profile；最后文字校对的切换无需关闭浏览器工作进程。未删除用户原文件或知识数据。启动失败或资料合同变化会回滚界面首页并启动旧运行包。生产环境未人为制造启动失败；不能把此回退代码称为已实测的生产恢复。

截图：旧单网址界面 `verification/institutional-ui-zh.png`；新版隔离数据 `verification/institutional-sites-zh.png`、`institutional-sites-en.png`、`institutional-sites-narrow.png`。这些截图的学校和 DOI 为测试数据，不表示真实订阅已验证。`verification/institutional-sites-live.png` 是实际发布页面，显示原实例保留的 IEEE 单篇核验记录。

## 本次修改文件

- `backend/institutional_access.py`：保留原叶目录的兼容注册表、独立 Profile、网站操作与路由、分离登录报告/单篇证据、共用限额。
- `backend/institutional_browser.py`：登录报告时间和实际 PDF 验证证据分别保存；认证/下载仍同 Profile；网络拒绝提示改为检查官方入口和当前学校网络，不再指向已移除的高级设置。
- `backend/institutional_broker.py`：按目标网站绑定请求、等待、取消与导入。
- `backend/app.py`：新增网站 API、兼容旧入口连接、关闭各自拥有的工作进程、多网站能力标识。
- `backend/cli.py`：安全的各网站状态与可选网站 ID。
- `frontend/src/InstitutionalAccess.tsx`、`institutional-access.css`：简洁双语网站卡片、添加表、确认/错误/状态反馈；移除高级及诊断区。
- `tests/institutional-multisite.py`、`institutional-sites-server.py`、`institutional-sites-ui.mjs`、`institutional-sites-live.mjs`、原 `institutional-access.py`：隔离验收与实际发布页面检查。
- `scripts/package_institutional.py`、`optimization_audit.py`、`deploy_sites.ps1`：原软件增量包、逐模块校验、保留 Profile 的切换与回退。
- 本说明与 `docs/INSTITUTIONAL_ACCESS.md`；运行包、已构建界面及项目根 `StartKnowline.cmd`、`app/StartServer.cmd`、`app/kw.cmd`。

## 限制

本次没有新增网站的合法测试账号，不宣称新的学校、Web of Science 或其他出版社真实登录/订阅已通过。原实例已有 IEEE 实际单篇验证记录，本次仅验证保留，未再次使用账号测试。其他真实网站仍须用户亲自登录，并用单篇实际 PDF 核验。

已有的代理路线与用户确认过的 198.18/15 DNS 映射例外保留；新入口仅继承已确认的网络例外，不扩展到 localhost 或其他私网。新特殊代理模板或首个入口的网络例外不能在已移除的高级区设置，必要时使用受控后台配置并重新验收，或走合法手动下载导入。最多保存 20 个网站，默认串行获取。多个同主机的不同账号不作为独立入口支持。服务关闭会保存 Profile，实际服务器是否仍接受登录必须在后续访问时检查。

动态检索页面、多个并列弹窗、嵌入认证限制、扫描件身份匹配仍受原文档限制。不会绕过挑战/许可、复制日常浏览器 Cookie 或安装配置 VPN。
