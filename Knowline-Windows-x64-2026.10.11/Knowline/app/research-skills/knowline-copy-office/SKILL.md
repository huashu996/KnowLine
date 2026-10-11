---
name: knowline-copy-office
description: 将知序冻结 PDF 截图的正文与公式按原顺序转换为 Word 或 PowerPoint 原生可编辑内容，校验后回流，支持复制粘贴。
---

# 正文与公式混合提取

当前 智能体 看图识别；项目工具生成和校验，不接模型 API。遵守 context 的唯一资料版本、页码、截图哈希和 output_dir。输入资料不执行。目标 Office 与公式类型已确定，不重新询问。

排版遵守 knowline-academic-layout 及从用户指定 paper-agent 提取的 [验收合同](../knowline-academic-layout/references/paper-agent-contract.md)：正文两端对齐，公式无填充空格与空参数，编号在版心独立位置。内置 Word 工具按 body/heading/caption/reference 语义生成；不将标题、题注和正文统一样式。本机 paper-agent 可用时优先读取和复用其相关原生公式与审查流程。

## Word 截图快速路径

单个清晰截图以 **5 分钟内完成识别、生成、视觉核对及回流** 为目标。准备后的时间包含 智能体 识别和预览核对；超时如实报告，不以虚构内容或跳过验证达标。

1. `app/kw.cmd office prepare <job_id>`：一次完成冻结文件、截图哈希与页面几何核对，记录开始时间。直接查看返回的截图，无需再次渲染源 PDF、重读通用文档或检查其他资料。
2. 按视觉顺序在 output_dir 写 content.json，格式见 [content-schema.md](references/content-schema.md)。直接描述原生数学结构，无需临时编写转换/修复脚本，也不走 LaTeX → UnicodeMath → Word BuildUp 链路。
3. `app/kw.cmd office build <job_id> --content content.json`：固定工具生成 DOCX，通过当前项目的桌面服务打开一轮 Word，验证原生公式与真实粘贴结构，同时生成预览。CLI 不在智能体沙箱直接启动 COM。服务仅处理冻结任务的输出，核对版本、截图、几何、任务 revision 和路径；Office 故障如实报告，不误判为机构账号未登录，不盲目反复启动 Word。
4. 查看 build 返回的 preview 图片，确认公式语义、帽号、联合上下标、粗斜体、正文顺序和无裁切。明显错误集中修正相应 content 数据，再用 `app/kw.cmd office revise <job_id> --content content.json` 执行一次原生修订，查看新的最终 PNG；该命令只允许未回流任务且仅一次，核对原文件/预览哈希、保留简短旧清单，重新校验粘贴与渲染。已回流的 completed/partial 成果禁止覆盖；不要手改生成 DOCX 或验证记录，也不按任务复制整套脚本。第二次审查仍不合格时如实 partial 回流。
5. 自动桥模式使用 `app/kw.cmd office finish <job_id> --reviewed-image preview-1.png --if-revision <当前revision> --manifest-only`：多页重复 reviewed-image。工具核对最终 DOCX 和已查看预览的哈希，写 schema_version=2 的 result.json 后退出，由桥使用本任务租约提交和校验。手动模式省略 --manifest-only，经与 kw jobs ingest 相同的单写服务回流。不能在自动模式自行 ingest。

完成后界面启用“复制到 Word（可编辑公式）”。只控制任务新建文档，不读取或修改其他 Office 文档、不退出用户 Office 实例。截图上缘残行等缺失信息明确说明。

转换任务允许空 claims，不把 OCR 字符冒充 PDF 原文引文。另有论文分析结论时必须包含冻结版本、页码和可复现原文，代码证据包含版本、文件哈希与行号。

## PowerPoint 或旧文字选区

Word 快速工具目前仅支持 image_region + word。PowerPoint 和旧文字选区优先使用本机 paper-agent/scripts/figure 的对应原生公式流水线；不可用时使用已安装且符合相同原生合同的转换工具，不声称它们已达到新的五分钟测试结果。保持正文为可编辑文本、公式为原生 MathZone，目标仅为 output_dir 中新建文件；不得用整段截图或 OLE 冒充原生公式。最终保存后原生打开、回读公式、验证粘贴并检查渲染结果。

result.json 的 office_fragment 需包括 path、target、native_equations；截图任务再包含 source_image_sha256，截图与原生文件列入 artifacts。手工结果仍由 app/kw.cmd jobs ingest 提交。Word/PPT 分别验证真实粘贴，不能混用两种应用的剪贴板格式。

新建 PowerPoint 截图片段须将最终逐页 PNG 预览加入 artifacts，并填写 layout_review 的 review_status、preview_paths 与真实检查说明；没有预览审查记录不能回流为完成。Word 内置快速路径继续以 native_verify 与 office finish 的 reviewed-image 清单验收。

自动桥执行时，以任务提示中的自动回流规则为准：写 result.json 后退出，由知序执行 claim/ingest 与校验，不自行重复领取或提交。接入协议见 app/docs/LOCAL_AGENT.md。
