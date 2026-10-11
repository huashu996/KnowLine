# 精简运行包 / Compact runtime distribution

保留桌面 EXE、必要原生依赖、编译后的界面、PDF 解析、离线语义检索模型、任务辅助工具、Office 原生工具、可信研究技能和使用说明。

发行包不包含 Node.js 开发依赖、前端开发工程、测试工程、调试报告、旧 EXE、个人论文、知识库、任务记录、机构会话或本地智能体适配配置。首次启动自行初始化空目录。不要把使用过的整个目录再次压缩给别人；那会包含自己的资料与设置。

The runtime distribution retains the desktop executable, native dependencies, built interface, PDF parser, offline retrieval model, task helpers, native Office helpers, trusted research skills and user documentation. Development projects, test fixtures, previous executables and personal state are excluded. A used installation can contain private resources and settings; distribute the clean release archive instead.

每个文件的 SHA256 和长度记录在发行包根目录 `RELEASE_MANIFEST.json`，便于验证解压完整性。正式运行无需前端编译或开发依赖安装。
