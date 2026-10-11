# 知序 2026.10.11 发行说明 / Release notes

修复 PDF 身份校验、星图进度产物入库校验、Word 原生渲染和公式首次失败后的修订恢复。智能体任务无总执行时限，多个任务可同时执行，重启后恢复本项目绑定。

Fixed PDF identity validation, graph enrichment acceptance, native Word rendering, and recovery of a failed initial formula build. Agent tasks run without an overall deadline, support concurrent execution, and restore this installation's binding after restart.

已执行两轮真实验收：每轮视觉 SLAM 10 篇全文、FAST-LIO 论文星图、3 个论文图复刻和 3 个公式复制任务。测试中发现的公式失败已修复并重试。完整性与视觉审查保持启用。

Two real acceptance rounds covered 10 Visual SLAM full texts, a FAST-LIO paper graph, three figure replications and three formula-copy tasks per round. A formula failure found during testing was fixed and retried. Integrity and visual review checks remain enabled.

公开来源可能没有某些论文全文，原图截断或重叠的标签也可能只能保留图片层。任务明确记录这些缺项；部分成果不等于所有 PDF 或所有文字均已取得。实际取得的 PDF 版本与正式书目分别保存。

Some papers have no accessible public full text, and clipped or overlapping source labels may remain separate image layers. Tasks report these limitations explicitly. Partial results do not imply that every PDF or every editable label is available. Acquired PDF versions and formal bibliographic records are recorded separately.

发行包仅包含必要运行文件和空用户目录。没有论文、任务、智能体凭据、机构登录会话或开发缓存。解压后运行 StartKnowline.cmd；首次使用请通过自己的本地智能体连接此安装。原生 Office 功能需要本机已安装的 Microsoft Word / PowerPoint。

The package contains runtime files and empty user folders only, with no papers, tasks, agent credentials, institutional sessions or development caches. Extract and run StartKnowline.cmd, then connect your own local agent to this installation. Native Office features require Microsoft Word / PowerPoint installed locally.
