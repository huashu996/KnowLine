# Word 快速提取内容格式

在任务 output_dir 写 content.json。格式是数据，不能包含 Python、脚本、原始 XML 或 hooks。工具不会执行输入。

```json
{
  "schema_version": 1,
  "source_image_sha256": "从 context.office_selection.image 复制",
  "source_version_id": "从 context.resources[0] 复制",
  "math": {
    "x": {"sub": ["x", "i"]},
    "formula": ["y = ", {"root": [{"frac": ["a", "b"]}, {"frac": ["c", "d"]}]}]
  },
  "blocks": [
    {"runs": ["Plain text ", {"math": "x"}, " continues."]},
    {"equation": "formula", "number": "2"}
  ],
  "uncertain": []
}
```

字符串代表数学字符；数组代表依次并列，相乘的两个分式用两个 frac 并列。段落中的 math 和公式行的 equation 接受定义名，或直接接受结构对象/数组；表达式中的 ref 可复用定义。重复符号定义一次，不复制深层结构；一次性表达式直接内联，例如 {"runs":["Where ",{"math":{"sub":["x","i"]}}," is known."]}。纯数学字符串须定义名称再引用，或内联 {"text":"i"}（正体）。不要另存一份识别原稿。保持原文顺序和编号，无法辨认处在正文标“待核对”并加入 uncertain。

| 表达式 | 含义 |
|---|---|
| `{"sub":[base,index]}` / `{"sup":[base,index]}` | 上下标，仅 index 是脚标 |
| `{"subsup":[base,lower,upper]}` | 同一基符号的联合上下标；嵌套 sup(sub(base,lower),upper) 也会生成此结构 |
| `{"pre":[base,left_lower,left_upper]}` | 左脚标；可用空串省略一侧，两侧不能同时为空；基底可包含右侧脚标 |
| `{"underbrace":[body,label]}` / `{"overbrace":[body,label]}` | 原生伸缩括注及下/上方标签 |
| `{"frac":[numerator,denominator]}` | 分式 |
| `{"root":body}` | 根号，可含并列数组 |
| `{"sum":{"lower":"l=0","upper":"L","body":expression}}` | 求和，可在 body 嵌套求和 |
| `{"integral":{"lower":"0","upper":"1","body":expression}}` | 积分 |
| `{"product":{"lower":"k=i","upper":"j−1","body":expression}}` | 原生连乘及上下限 |
| `{"delim":["(",body,")"]}` | 伸缩括号，支持 []、{}、绝对值及范数 |
| `{"func":["cos",argument]}` | 正体函数 sin/cos/tan/log/ln/exp/min/max/lim/det |
| `{"matrix":[[a,b],[c,d]]}` | 矩阵，可外包 delim |
| `{"bold":"H"}` / `{"bold_upright":"H"}` | 粗斜体数学变量 / 明确需要正体的粗体符号 |
| `{"hat":base}` / `{"bar":base}` / `{"tilde":base}` / `{"dot":base}` / `{"ddot":base}` / `{"vec":base}` | 原生数学重音；T̂ 等组合字符也会转换为真正重音结构 |
| `{"ref":"definition_name"}` | 引用定义，禁止循环 |
| `{"text":"if applicable"}` | 公式内正体文字，保留必要单词间距 |

文本块可指定 role=body/heading/caption/reference。正文默认两端对齐，标题和题注使用独立语义样式，参考文献使用悬挂缩进。公式字符串会去除首尾和重复空白，不使用空格串定位；分式和上下标参数必须非空。积分或求和省略上下限时，用空字符串表示隐藏该上下限，不能创建可见空虚框。公式编号的制表位由 A4 版心宽度定位，不会超出右页边。
