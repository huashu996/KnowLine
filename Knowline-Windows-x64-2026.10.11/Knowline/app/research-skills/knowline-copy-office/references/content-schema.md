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

字符串代表数学字符；数组代表依次并列，相乘的两个分式用两个 frac 并列。段落中的 math 和公式行的 equation 引用定义名；表达式中的 ref 可复用定义。保持原文顺序和编号，无法辨认处在正文标“待核对”并加入 uncertain。

| 表达式 | 含义 |
|---|---|
| `{"sub":[base,index]}` / `{"sup":[base,index]}` | 上下标，仅 index 是脚标 |
| `{"subsup":[base,lower,upper]}` | 同一基符号的联合上下标；嵌套 sup(sub(base,lower),upper) 也会生成此结构 |
| `{"frac":[numerator,denominator]}` | 分式 |
| `{"root":body}` | 根号，可含并列数组 |
| `{"sum":{"lower":"l=0","upper":"L","body":expression}}` | 求和，可在 body 嵌套求和 |
| `{"integral":{"lower":"0","upper":"1","body":expression}}` | 积分 |
| `{"delim":["(",body,")"]}` | 伸缩括号，支持 []、{}、绝对值及范数 |
| `{"func":["cos",argument]}` | 正体函数 sin/cos/tan/log/ln/exp/min/max/lim/det |
| `{"matrix":[[a,b],[c,d]]}` | 矩阵，可外包 delim |
| `{"bold":"H"}` / `{"bold_upright":"H"}` | 粗斜体数学变量 / 明确需要正体的粗体符号 |
| `{"hat":base}` / `{"bar":base}` / `{"tilde":base}` / `{"dot":base}` / `{"ddot":base}` / `{"vec":base}` | 原生数学重音；T̂ 等组合字符也会转换为真正重音结构 |
| `{"ref":"definition_name"}` | 引用定义，禁止循环 |
| `{"text":"if applicable"}` | 公式内正体文字，保留必要单词间距 |

文本块可指定 role=body/heading/caption/reference。正文默认两端对齐，标题和题注使用独立语义样式，参考文献使用悬挂缩进。公式字符串会去除首尾和重复空白，不使用空格串定位；分式和上下标参数必须非空。积分或求和省略上下限时，用空字符串表示隐藏该上下限，不能创建可见空虚框。公式编号的制表位由 A4 版心宽度定位，不会超出右页边。
