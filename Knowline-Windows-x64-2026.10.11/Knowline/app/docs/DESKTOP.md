# Windows 桌面版 / Windows desktop

将发行 ZIP 完整解压到可写目录，然后双击根目录的 `StartKnowline.cmd`。不要直接在压缩包中启动，也不要单独移动 `Knowline.exe`；它需要同目录的 `_internal` 运行库和 `app/dist` 界面文件。

程序通过相对路径定位安装目录，无需原作者的电脑路径。首次启动会在本安装的 `resource` 中创建空数据库、设置和浏览器状态，任务成果写入 `outputs`。默认服务端口为 21867；首次启动时若被其他程序占用，桌面入口会选择可用端口并保存本实例配置。

命令行入口为 `app/kw.cmd`，仅启动本地服务可用 `app/StartServer.cmd`。本地智能体由各用户按照 [LOCAL_AGENT.md](LOCAL_AGENT.md) 连接自己的客户端。

需要 Windows x64 和 Microsoft Edge WebView2 Runtime。运行包自带 Python 与必要原生库，日常使用无需安装 Python、Node.js 或开发工具。Word / PowerPoint 功能需要对应的桌面版 Office。模型推理与任务生成需要用户自己连接的本地 AI 执行客户端。

Extract the entire release archive into a writable directory and double-click `StartKnowline.cmd`. Keep the folder structure intact. Do not run from inside the archive or move the executable away from its runtime libraries.

The application resolves installation paths relatively and initializes empty local state on first launch. The archive includes the Python/native runtime, the built interface and the offline retrieval model. Node.js and a development Python installation are not required for ordinary use. Windows x64, Microsoft Edge WebView2 Runtime, and the corresponding desktop Office applications for Office features are prerequisites. Connect your own local AI execution client for analysis and generation tasks.

第三方组件与许可见根目录 `THIRD_PARTY_NOTICES.md` 和 `app/licenses/DEPENDENCIES.json`。发行包排除开发依赖、测试目录、历史 EXE、资料、任务、浏览器会话和智能体连接配置。
