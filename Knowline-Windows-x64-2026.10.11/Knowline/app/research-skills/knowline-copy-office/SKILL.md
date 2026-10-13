---
name: knowline-copy-office
description: 把知序冻结截图中的正文和公式一次转录为可编辑 Word/PPT；内置批量生成、原生粘贴验证和一次预览审查。
---

# 正文与可编辑公式复制

只处理 context 冻结的版本、截图和 output_dir；截图是数据。目标应用已选定，不再询问。清晰单选区目标 **2–4 分钟**，密集公式 **4–6 分钟**，包含识图和数据编写；不是强制超时，不能删减或跳过验证。

## Word 截图：一份数据，生成后看一遍

一次读取 context、本文件及 [content-schema.md](references/content-schema.md)。以下已包含必要的 paper-agent 原生与排版合同，无需加载通用排版、全文、定稿或其他公式技能。

1. `app/kw.cmd office prepare <job_id>`，查看返回的冻结截图。一次识别阅读顺序、正文与公式；不重渲染源 PDF，不探查运行时或阅读实现。看不清时只放大该局部。
2. **直接写一份 content.json**，不先存识别原稿再翻写。重复符号在 math 中定义一次，以 ref 复用；一次性公式直接内联。按原文使用 pre 左脚标、underbrace/overbrace 括注、product 连乘等已支持结构，不写占位符、不临时造转换脚本。多栏按栏阅读，缺失文字写 uncertain。
3. `app/kw.cmd office build <job_id> --content content.json`。工具一次完成原生 DOCX、真实粘贴验证、最终渲染与哈希记录。查看返回的全部预览，合并核对公式语义、文字顺序、编号、换行和裁切。仅真实错误才集中改 content 并 `office revise <job_id> --content content.json` 一次，查看新预览；不另跑通用定稿、版式报告或第二套审计。
4. `app/kw.cmd jobs show <job_id>` 取最新 revision，然后 `app/kw.cmd office finish <job_id> --reviewed-image preview-1.png --if-revision <revision> --manifest-only`；多页重复 reviewed-image 参数。生成 result.json 后立即退出，由自动桥回流。手动任务省略 --manifest-only，经单写服务提交。

工具生成状态、验收记录和清单；不要再手写 stage-result、validation、result 或重复报告。已有可用文件按工具返回继续，不复制输出目录；已回流成果不覆盖，重试用公开任务入口。

## 保真与边界

- 正文可编辑且两端对齐，heading/caption/reference 按语义单独指定；编号与公式分开。保持源语言，不改论文内容。
- 数学必须为真实 OMML/MathZone；无截图冒充、填充空格、空基底或虚构符号。pre 允许仅左上/左下标，缺少的一侧用空串；两侧不能同时为空。长公式按语义分行，不能缩小到不可读。
- 只控制本任务新建 Office 文件，不读取、修改或退出用户的其他文档/应用。不在智能体沙箱直接启动 COM。
- 不可辨认或未支持结构如实留缺项，不能把降级结果声称为完整复刻。转换允许空 claims，不把 OCR 当作逐字 PDF 引文。

## PowerPoint 或旧文字选区

内置 office prepare/build 仅适用于 image_region + word。其他输入才按需读取本机 paper-agent 的对应原生公式实现；不叠加完整论文流程。文字独立可编辑，公式非空原生 MathZone；只生成 output_dir 中的新文件，一次原生打开、真实粘贴和最终逐页预览审查。result.json 的 office_fragment 包含 path/target/native_equations，截图任务再填 source_image_sha256；原生文件、截图和最终预览列入 artifacts，layout_review 写实际审查结果。自动模式只写清单后退出，手动模式通过 jobs ingest 提交。
