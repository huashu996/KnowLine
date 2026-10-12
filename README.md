# 知序 · Knowline

**把论文、代码、知识与科研成果连接起来的本地研究工作台。**  
**A local research workspace connecting papers, code, knowledge and research outputs.**

[中文](#中文说明) · [English](#english)

**Windows x64 · 2026.10.11**

本仓库提供精简运行版。通过 **Code → Download ZIP** 下载并完整解压，进入 `Knowline-Windows-x64-2026.10.11/Knowline`，双击 `StartKnowline.cmd`。需要 Windows x64 与 Microsoft Edge WebView2 Runtime；使用 Office 功能时还需要对应的桌面版 Word / PowerPoint。

2026-10-12 源码同步：上述目录中的 `app/backend`、`app/frontend`、研究技能及脚本已同步本地更新。此次仅发布源码和界面素材，保留 2026.10.11 打包运行程序与已构建界面；直接启动 EXE 不会自动加载全部新源码。用户资料、成果、登录会话、本机配置与开发缓存均未上传。

Source sync (2026-10-12): application sources, frontend assets, research skills and scripts have been updated in the existing directory. The bundled executable and built interface remain the 2026.10.11 release; launching the EXE does not automatically load all source changes. Personal resources, outputs, sessions, local configuration and development caches are excluded.

Download the repository with **Code → Download ZIP**, extract the entire archive, open `Knowline-Windows-x64-2026.10.11/Knowline`, and double-click `StartKnowline.cmd`. Windows x64 and Microsoft Edge WebView2 Runtime are required; Office features require the corresponding desktop Word / PowerPoint installation.

软件内容位于 [`Knowline-Windows-x64-2026.10.11`](Knowline-Windows-x64-2026.10.11)，本 README 位于仓库根目录。发行内容不包含用户资料、任务、机构登录会话或智能体连接配置。


## 中文说明

知序是一款 Windows 桌面研究工具，将资料管理、文献探索、分层知识库、动态引用和科研成果制作放在同一个工作空间中。资料与成果保存在本机，需要理解和生成内容的任务由项目绑定的本地智能体执行。

### 功能一览

| 功能 | 可以做什么 |
| --- | --- |
| **论文与代码资源库** | 通过文件选择器导入多个 PDF、PDF 文件夹、代码源文件或项目目录；保留代码目录结构，按内容去重，通过领域、标签和笔记组织资料。 |
| **PDF 与代码阅读** | 连续阅读 PDF、缩放、选区、高亮和批注；浏览代码目录、带行号的源码并调整字号。论文页码和代码行号可作为任务证据。 |
| **论文检索与论文星云图** | 按主题、年份和数量要求探索论文，从起点论文查看关联文献、摘要与来源，将选中候选导入资源库或指定领域。 |
| **PDF 获取与摘要提取** | 复用已有全文；对应账户已登录时优先尝试正式出版版，未登录或获取失败时继续寻找合法公开全文。生成星图时同步尝试获取 PDF，从可用 PDF 提取摘要并记录来源页码。 |
| **书目核验与引用导出** | 核对题名、作者、年份、刊会、DOI 和版本关系，分别记录正式书目与实际 PDF 版本；更新引用信息，导出文本、RIS 或 JSON 引用记录。 |
| **分层知识库与知识网络** | 从选定论文和代码建库，自定义各层名称与侧重点；生成带来源的知识卡片、关联和图像，浏览知识网络，使用原文检索及关键词、语义与关联融合的知识检索。 |
| **知识库导入与更新** | 点击“导入知识库”直接打开 Windows 文件夹选择窗口，无需手填路径；导入受支持的知识库目录，或添加资料并更新已有库。 |
| **资料理解与方法分析** | 对明确选定的资料创建阅读、分析、翻译或方法比较任务，生成可追溯到原论文或源码的成果。 |
| **正文与可编辑公式** | 选取论文区域，制作 Word 或 PowerPoint 正文与公式成果，使用原生可编辑公式并检查真实文件和预览。 |
| **可编辑论文图复刻** | 将论文选区制作成 PowerPoint 图，使用独立文字、框体、连接线与图片层，保留来源和最终预览，便于继续修改。 |
| **科研方案工作台** | 输入研究想法，选择论文、代码、知识库或其组合，生成 Word / PowerPoint 方案；基于上一轮成果继续优化，保留各轮来源与产物。 |
| **Word 动态引用** | 连接指定 Word 文档，从已核验来源插入引文与参考文献；支持数字上标、IEEE、APA 和本机 GB7714 样式，以及编号更新、字体字号设置和引用跳转。 |
| **机构访问** | 管理多个学校、出版社或数据库的官方入口，在各自专用窗口完成登录，后续任务复用对应站点会话。 |
| **并行智能体任务** | 一次连接可复用的本地智能体执行入口，多个任务可同时执行；每份任务有独立范围、状态、取消控制、执行记录、电脑本地运行时间、用时和成果校验。 |
| **语言联动与存储管理** | 界面语言设置联动新任务的成果目录、自动文件名与说明文字；下载保存名跟随当前语言。支持存储统计、缓存预算、安全清理预览和元数据检查点。 |

### 快速开始

使用发行 ZIP 时，先将整个压缩包解压到可写目录，再启动。第三方组件及许可说明见 [THIRD_PARTY_NOTICES.md](Knowline-Windows-x64-2026.10.11/Knowline/THIRD_PARTY_NOTICES.md)。

1. 双击项目根目录的 **`StartKnowline.cmd`**，打开知序桌面版。
2. 在资源库点击“导入资源”，选择论文 PDF、文件夹或代码，按需要加入领域。
3. 阅读资料，或进入“查找新论文”探索文献与论文星云图。
4. 创建或导入知识库，配置知识层与侧重点。
5. 需要智能体分析或生成成果时，在自己的本地 AI 项目中说：**“将本地智能体连接到知序”**。详见 [本地智能体协议](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/LOCAL_AGENT.md)。
6. 在“智能体任务”查看进度与成果，或进入“方案”工作台继续制作科研方案。

默认本地地址为 **[http://127.0.0.1:21867/](http://127.0.0.1:21867/)**。仅启动服务可运行 `app/StartServer.cmd`；本实例使用配置中的端口。

### 运行条件与使用说明

- **Windows 桌面环境：** 需要 Microsoft Edge WebView2 Runtime。打包版本自带程序运行依赖，日常使用无需安装 Node.js 或 Python 开发环境。
- **Office 功能：** 原生文档、公式、图形与动态引用需要对应的 Windows 桌面版 Microsoft Word / PowerPoint；Office 不随知序提供。
- **智能体执行：** 需要已配置、具有文件和科研工具能力、可重复调用的本地执行客户端。“本地”指工具执行环境，模型可以使用客户端已配置的云服务；普通网页聊天窗口不能直接充当持续执行入口。
- **全文与摘要：** 获取结果取决于网络、来源开放程度、机构权限和 PDF 文本层。未取得 PDF 或未能提取摘要时，保留已有信息并显示缺项，不保证任意论文都能取得全文。
- **知识库导入：** 选择包含 `.rag.manifest.json` 的受支持知识库目录。普通资料文件夹请通过资源导入后再建库。
- **成果核验：** 完成状态依据实际文件、哈希、范围和来源证据；Office 成果还需要相应的结构与预览审查。元数据检查点记录状态信息，不是完整文件备份。

系统生成名称随语言设置联动；论文原始题名、引用原文和历史已登记文件保持原样。切换语言后下载同一成果可以使用新的保存名，文件内容保持一致。

### 文件保存在哪里

```text
Knowline/
├── StartKnowline.cmd       # 桌面启动入口
├── README.md              # 中英文功能与使用说明
├── app/                   # 程序、运行库、CLI、文档与研究技能
├── resource/              # 本实例的资料、知识库、索引和任务状态
│   ├── incoming/          # 导入资料与下载的源 PDF
│   ├── library/           # 导入的知识库
│   └── .knowledge/        # 数据目录、版本与运行状态
└── outputs/               # 按任务保存的 Word、PPT、报告与预览成果
```

### 工具与文档

先进入 `Knowline-Windows-x64-2026.10.11/Knowline` 目录，再使用 PowerShell：

```powershell
.\app\kw.cmd --help
.\app\kw.cmd agent status
```

- [桌面启动与运行包](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/DESKTOP.md)
- [本地智能体连接与并行执行](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/LOCAL_AGENT.md)
- [代码文件与项目目录导入](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/CODE_IMPORT.md)
- [知识卡片与来源](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/KNOWLEDGE_CARDS.md)
- [Word 动态引用](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/WORD_CITATIONS.md)
- [正式引用记录与 PDF 版本](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/CITATION_PDF_SEPARATION.md)
- [科研方案的来源选择](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/PROPOSAL_SOURCES.md)
- [CLI / API 协议](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/PROTOCOL.md)

## English

Knowline is a Windows desktop research workspace for managing resources, exploring literature, building layered knowledge bases, maintaining citations and producing research documents. Resources and outputs are stored on your computer. Tasks requiring interpretation or generation run through the local agent connected to the project.

### Features

| Feature | What you can do |
| --- | --- |
| **Paper and code library** | Import multiple PDFs, PDF folders, source files or project directories through file pickers. Preserve code directory structure, deduplicate content and organize resources with domains, tags and notes. |
| **PDF and code readers** | Read continuous PDF pages, zoom, select regions, highlight and annotate. Browse source trees and code with line numbers, adjust font size and use paper pages or code lines as task evidence. |
| **Paper discovery and Paper Star Map** | Explore papers within a topic, year range and target count. View related literature, abstracts and sources from a seed paper, and import selected candidates into the library or a domain. |
| **PDF acquisition and abstract extraction** | Reuse saved full texts. Try the formal publisher version first when the corresponding account is signed in; otherwise, or after acquisition fails, continue with legally available public copies. Attempt PDF acquisition during star map generation and extract abstracts from available PDFs with page provenance. |
| **Bibliographic verification and citation export** | Verify titles, authors, years, venues, DOIs and version relationships. Track formal publication metadata separately from the actual PDF version, refresh citation information and export text, RIS or JSON records. |
| **Layered knowledge bases and networks** | Build from selected papers and code, define layer names and focus areas, and generate sourced knowledge cards, links and figures. Explore the knowledge network and use source-text search alongside keyword, semantic and link-based knowledge retrieval. |
| **Knowledge base import and updates** | Click Import knowledge base to open the Windows folder picker without entering a path. Import a supported knowledge base directory, or add resources and update an existing base. |
| **Resource understanding and method analysis** | Create reading, analysis, translation and method-comparison tasks for an explicit resource selection, with outputs traceable to the original papers or code. |
| **Text and editable equations** | Turn selected paper regions into Word or PowerPoint text and equation outputs using native editable equations, with actual file and preview checks. |
| **Editable paper figure reconstruction** | Reconstruct a selected paper figure in PowerPoint with separate text, shapes, connectors and image layers, retaining the source and final previews for further editing. |
| **Research proposal workspace** | Develop an idea using papers, code, knowledge bases or a combination. Generate Word / PowerPoint proposals and refine previous rounds while retaining their sources and outputs. |
| **Dynamic Word citations** | Connect a selected Word document and insert citations and bibliographies from verified sources. Use numbered superscripts, IEEE, APA or locally installed GB7714 styles, update numbering, adjust typography and follow citation links. |
| **Institutional access** | Manage official entries for multiple institutions, publishers or databases. Sign in through dedicated windows and let subsequent tasks reuse the matching site session. |
| **Concurrent agent tasks** | Connect a reusable local execution client once and run multiple tasks concurrently. Each task has its own scope, status, cancellation controls, execution history, computer-local run time, duration and output validation. |
| **Language-aware naming and storage management** | The interface language controls new output directories, generated filenames and descriptions. Download names follow the current language setting. Inspect storage usage, configure cache budgets, preview safe cleanup and record metadata checkpoints. |

### Quick start

Extract the entire release ZIP into a writable directory before launching. See [THIRD_PARTY_NOTICES.md](Knowline-Windows-x64-2026.10.11/Knowline/THIRD_PARTY_NOTICES.md) for third-party component and licensing notices.

1. Double-click **`StartKnowline.cmd`** in the project root to open the desktop application.
2. Click Import resources and select PDFs, folders or code. Add resources to a domain if needed.
3. Read your resources or open Discover papers to explore literature and the Paper Star Map.
4. Create or import a knowledge base and define its layers and focus areas.
5. For agent analysis or generation, ask your local AI project: **“Connect the local agent to Knowline.”** See the [local agent protocol](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/LOCAL_AGENT.md).
6. Review progress and outputs in Agent tasks, or continue in the Proposal workspace.

The default local address is **[http://127.0.0.1:21867/](http://127.0.0.1:21867/)**. Run `app/StartServer.cmd` to start only the local service. The instance uses its configured port.

### Requirements and usage notes

- **Windows desktop:** Microsoft Edge WebView2 Runtime is required. The packaged application includes its runtime dependencies; ordinary use does not require a Node.js or Python development installation.
- **Office features:** Native documents, equations, figures and citations require the corresponding Windows desktop version of Microsoft Word / PowerPoint. Office is not included.
- **Agent execution:** Use a configured local client with a repeatable execution interface and the required file and research tools. “Local” refers to tool execution; the client may use its configured cloud model. An ordinary web chat cannot serve as a persistent execution client.
- **Full texts and abstracts:** Availability depends on network access, public sources, institutional permissions and PDF text layers. Missing PDFs or abstracts remain explicitly marked; acquisition of every paper is not guaranteed.
- **Knowledge base import:** Select a supported knowledge base directory containing `.rag.manifest.json`. Import an ordinary document folder as resources before building a knowledge base.
- **Output validation:** Completion depends on actual files, hashes, scope and source evidence. Office outputs also require the applicable structural and preview review. A metadata checkpoint records state information and is not a full file backup.

Generated names follow the language setting. Original paper titles, quoted source text and previously registered files remain intact. Changing the language can change the saved download name of the same output without changing its contents.

### Storage layout

```text
Knowline/
├── StartKnowline.cmd       # Desktop launcher
├── README.md              # Bilingual feature and usage guide
├── app/                   # Application, runtime, CLI, documentation and research skills
├── resource/              # This instance's resources, knowledge bases, indexes and task state
│   ├── incoming/          # Imported resources and downloaded source PDFs
│   ├── library/           # Imported knowledge bases
│   └── .knowledge/        # Catalog, versions and runtime state
└── outputs/               # Word, PPT, reports and previews organized by task
```

### Tools and documentation

From the `Knowline-Windows-x64-2026.10.11/Knowline` directory in PowerShell:

```powershell
.\app\kw.cmd --help
.\app\kw.cmd agent status
```

The following technical documents are currently primarily in Chinese:

- [Desktop startup and packaged runtime](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/DESKTOP.md)
- [Local agent connection and concurrent execution](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/LOCAL_AGENT.md)
- [Source file and project directory import](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/CODE_IMPORT.md)
- [Knowledge cards and provenance](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/KNOWLEDGE_CARDS.md)
- [Dynamic Word citations](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/WORD_CITATIONS.md)
- [Formal citation records and PDF versions](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/CITATION_PDF_SEPARATION.md)
- [Source selection for research proposals](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/PROPOSAL_SOURCES.md)
- [CLI / API protocol](Knowline-Windows-x64-2026.10.11/Knowline/app/docs/PROTOCOL.md)
