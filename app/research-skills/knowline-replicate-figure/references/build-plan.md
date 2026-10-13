# 一份源图计划，批量生成

坐标统一用冻结截图像素：`bbox=[左,上,宽,高]`，`start/end=[x,y]`；颜色为6位RGB；字号和线宽为源图物理pt。faithful按 source_size_pt 原大小居中，uniform才整体等比适配画布。不要再手工换算EMU或建立第二套坐标账本。

以下仅为格式示例，实际文字、坐标、颜色、数量必须由源图识别得出：

```json
{
  "source_image_sha256": "冻结来源图片的真实SHA256",
  "defaults": {"font":"Times New Roman", "font_size_pt":12, "stroke":"000000", "line_width_pt":1},
  "styles": {"module":{"fill":"E8F0FA", "align":"center", "valign":"middle"}},
  "objects": [
    {"name":"input", "kind":"rect", "style":"module", "bbox":[20,30,120,60], "text":"Input"},
    {"name":"output", "kind":"rect", "style":"module", "bbox":[220,30,120,60], "text":"Output"},
    {"name":"flow", "kind":"connector", "start":[140,60], "end":[220,60], "source":{"name":"input","site":3}, "target":{"name":"output","site":1}, "end_arrow":"triangle"}
  ],
  "axis_constraints":[{"source":"input","target":"output","axis":"horizontal"}]
}
```

对象以唯一 `name` 标识。`defaults → styles[style] → 对象字段` 逐级覆盖；相同模块共享样式。对象清单来自源图，不能从输出PPT反推期望数量。工具不做识图或质量判断，最终仍需实际看图。

| kind | 必要字段及用途 |
|---|---|
| rect / rounded_rect / ellipse / diamond / triangle / right_arrow / down_arrow / parallelogram | bbox；有文字就写 text 与 font_size_pt；圆角等预设可用 adjustment 设置首个调节点，adjustments:[...] 依次设置所有调节点 |
| text | bbox、text、font_size_pt；无框文字，stroke:null；原换行用 `\n` |
| connector | start/end、source/target 的 name/site；routing 为 straight、elbow 或 curved；真实关系使用连接器；elbow 可用 route_points 指定3–6个源坐标转折点 |
| bezier | commands 为源坐标命令列表，支持 M/L/C/Q，例如 [["M",10,20],["C",30,5,50,5,70,20]]；单个原生自由曲线；closed_fill:true 闭合并使用 fill 填色；兼容旧计划的 native_bezier 字段 |
| line / polyline / polygon | points:[[x,y],...]；polyline为单个开放原生路径，polygon为闭合形状；几何射线/装饰线不伪装成绑定连接器 |
| image | bbox；默认从冻结截图相同bbox裁剪，可用crop另指定源矩形；已有独立素材用项目相对asset + asset_sha256，须位于本任务输出目录 |
| formula | bbox、native_linear、font_size_pt；Office原生线性公式，首次批量构建后由桌面服务统一插入 |

矩形/椭圆的连接站点：0上、1左、2下、3右；其他预设先核对适用站点。start/end保持源图实际端点；只有确实共轴的模块才填 axis_constraints，投影射线不套模块共轴。

可选通用字段：`fill`（null透明）、`stroke`（null无线）、`line_width_pt`、`dash`（dash/dot）、`begin_arrow/end_arrow`（none/triangle/stealth/diamond/oval/arrow）、`rotation`（角度，仅形状/图片/文字/曲线，连接器由端点决定）、`layer`。工具按 background/path/node/complex_image/icon/text 排层，同层保持对象顺序；源图需特殊遮挡时按实际语义指定层。箭头默认细线配窄短头，禁止使用open枚举。

文字字段：font、font_size_pt、color、bold、italic、small_caps、align(left/center/right)、valign(top/middle/bottom)、margin_pt、line_spacing_pt；保留源字号和显式换行，默认不自动换行、行距为字号的固定pt。桌面准备仅按真实文字边界扩大无填充、无线条的文字框，保持文字中心和字号；不扩大可见模块框，不缩小文字以绕过验收。工具默认框内少量边距，源图有特定留白时显式设置。

复杂图片默认独立矩形裁剪；异形主体/遮挡需要时先一次批量完成必要抠图，再以asset插入。不拉伸照片、不裁入周围可分离标签，不为每张图额外保存定位图和局部审查图。工具拒绝整幅来源截图铺底。

不支持的特殊矢量、SVG或MathType才使用一个最小任务构建脚本补充，并相应补全同一原生审计清单；不得用折线或截图替代原曲线/公式，也不要为切换工具重建已有正确工作稿。审计清单的完整字段见[native-contract.md](native-contract.md)。

直接写计划数据即可。旋转、预设调节点、封闭曲线和图层已内置，不再为这些字段写 XML 后处理脚本。一次性对象只写与 defaults/styles 不同的字段；已有审查轮次不能通过重建来重置。
