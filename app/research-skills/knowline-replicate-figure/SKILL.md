---
name: knowline-replicate-figure
description: 忠实复刻知序冻结论文截图为可编辑单页PPT；一份对象计划、内置批量构建、一次合并审查后定稿。
---

# 论文图复刻

这是 replicate_paper_figure 的唯一流程，已吸收 paper-agent 的原生对象与快速生成要求。普通单页目标 **3–5 分钟**，复杂素材/公式 **5–8 分钟**，包含识图和计划编写；不是强制超时，不能为速度删减内容或降低验收。三个阶段由同一智能体完成，不启动额外智能体。

## 1. 看图，直接写对象计划

一次读取 context、本文件及 [build-plan.md](references/build-plan.md)，核对 figure_selection.image 的哈希并看冻结截图。截图即骨架；页面、比例、字号策略、公式模式、目标文件已冻结，不再确认、选模板或绘制骨架。

直接按截图像素坐标写一份 figure-plan.json，共享 defaults/styles；不先写生成计划的 Python，也不手写坐标转换或另一套对象账本。计划同时提供源文字、配色、层级、连接与预期对象数量。先看图再填数据；只有模糊字词或素材分离需要时读取冻结 PDF 的对应区域，不默认枚举整页路径、字形或逐字拟合像素。不可读处如实记录。

同页证据取一处短图题/邻近原文，原字符保留，finish 统一校验；没有疑点无需另跑 evidence。

## 2. 批量生成可编辑稿

用任务提示中的可信 Python：

```text
python app/scripts/figure_build.py <context绝对路径> <figure-plan绝对路径>
```

工具生成工作 PPT、来源对象登记、审计输入，并通过本实例桌面服务批量准备文字和公式。rotation、adjustments、closed_fill 和 layer 均已内置，直接声明，不为这些能力写后处理脚本。已有可用工作稿就续用；仅确实缺少的特殊能力才按需读 [native-contract.md](references/native-contract.md) 并补必要对象。

- 文字和基础图形原生可编辑；有框文字写入框体，无框文字独立。模块连接用真实锚点，折线为单个连接器；射线/投影按源斜率用单个原生路径，不套模块共轴规则。
- 独立照片/点云/复杂实验图按主体裁剪，外部文字、框线和箭头独立重建；优先复用用户素材，禁止整图铺底。简单图标用原生形状，复杂矢量才用独立 SVG。
- 保留文字、公式、配色、比例、拓扑与遮挡层级。源字号优先于10–28pt参考范围；不因通用留白指标改变正确源图。公式保持已选类型，不用文本或图片冒充。

## 3. 看一份合并预览，通过即回流

```text
python app/scripts/figure_workflow.py audit <context绝对路径> --manifest <native-audit-input绝对路径>
```

结构、原生回读和渲染由工具一次完成。查看返回的同一张 PNG，合并核对源内容、公式、箭头、色层、裁切和可编辑性；仅疑点放大，不再运行通用几何、像素碰撞或第二套审计。无实际缺陷不继续微调字体或虚线节距。

写 visual-review.json，值取本次 audit：

```json
{"presentation_sha256":"PPT哈希","preview_sha256":"PNG哈希","review_status":"passed","checks":{"source_fidelity":true,"text_and_formulas":true,"connections_and_arrows":true,"colors_and_layers":true,"visible_layout":true},"blockers":[],"notes":["实际核对结果"],"quote":"同页原文"}
```

```text
python app/scripts/figure_workflow.py finish <context绝对路径> --review <visual-review绝对路径>
```

finish 校验哈希和证据、按原字节发布并复用原生预览，自动生成 figure-review.json/result.json。自动任务立即退出，由桥回流；手动任务按提示提交。不再写成果报告、清单或调用 research_finalize，也不加载完整 paper-agent、Word 排版或通用定稿流程。

真实缺陷集中改一次，再用同一 audit 定向复核一次；相同输入复用有效记录。第二轮仍有阻断/环境不可用时保留工作稿、记录 blocker 并退出，不伪造通过。轻微非阻断差异用 passed_with_notes。不得删除状态、改名重建或增加审计来重置轮次；终止后重试只能走公开任务入口。

产物仅写 context.output_dir，编号只取 context.job_id，历史路径用 backend.safety.contained 解析。原生 Office 只控制本任务新建目标，不触碰其他演示文稿或退出用户实例。不改来源、程序和已登记成果。stage-result 由工具维护，计时包含识图/计划；用户说明遵守 ui_locale，源图文字不翻译。
