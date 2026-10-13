# 原生公式与合并审计输入

常见对象使用 figure_build.py 时，下述Office公式清单、原生插入和审计输入均由工具完成，无需手写或重复调用。仅特殊对象扩展或已有工作稿需要本参考。

工作副本是 context.figure_selection.target_pptx 同目录、同主干加 .working.pptx，例如“论文图复刻.working.pptx”。最终路径必须使用冻结 target。

## 公式：仅需要时读取

复用本机 Paper-framework-skill 的 LaTeX → Office manifest 转换脚本，不加载完整论文流程。Office manifest：mode="Office"，equations 每项有唯一 id、非空 native_linear、显式 font_size，target={type:"powerpoint_shape",slide_index:1,shape_name:"已存在占位框名"}。转换脚本可能不传递源字号；按 ID 补齐 font_size，不沿用默认20pt。

执行 `app/kw.cmd office native <job_id> --operation equations --presentation <项目相对工作PPTX> --manifest <项目相对公式JSON>`。服务负责原生插入；以实际非空 MathZones 回读为准。公式内容和文字保持源图语义，禁止连续空格、空上下标或图片替代原生公式。首次构建同时完成公式位置与图层。

失败只读 office-native-equations-process.json 或服务 diagnostic_path；先修正实际输入问题再重试，不对未改输入循环调用。

## 审计输入：一次写全

```json
{
  "slide_index": 1,
  "render_width": 1920,
  "render_height": 1080,
  "expected_slide_count": 1,
  "expected_shape_count": 3,
  "expected_image_count": 0,
  "expected_connector_count": 0,
  "expected_formula_count": 1,
  "expected_axis_constraint_count": 0,
  "delivery_gate": true,
  "require_full_registry": true,
  "objects": [
    {"name": "panel", "layer": "background"},
    {"name": "label", "layer": "text"},
    {"name": "formula", "layer": "text"}
  ],
  "expected_text": [{"name": "label", "text": "源图可读文字"}],
  "formula_objects": [{"name": "formula", "kind": "office"}],
  "axis_constraints": []
}
```

以上只是小型格式示例，全部期望数量、对象名与文字必须替换为源图账本的真实要求。layer 可用 background/path/node/complex_image/icon/text。适用的模块轴约束格式为 {source:"源形状名",target:"目标形状名",axis:"horizontal或vertical"}，原生工具以0.1pt作为轴偏差阈值。不要对几何投影射线强加模块共轴规则。没有公式或轴约束时对应数组为空、计数为0，并在账本说明适用范围。

渲染按页面比例默认约1920宽；仅微小标注确需更高分辨率时采用最高4096，两个维度均需320–4096。清晰度不足可查看同一PNG局部，不以分辨率名义重复渲染已清晰的图。

运行 figure_workflow.py audit，不再直接运行额外 audit 或外部通用几何检查器。原生审计检查数量、文字、公式、注册覆盖、图层、模块轴与连接端点；helper 补充真正生效的 OOXML 分支、非空公式与版面边界。源图保真、颜色填充和实际可见碰撞仍由智能体查看同一PNG确认，不能用结构通过冒充视觉通过。
