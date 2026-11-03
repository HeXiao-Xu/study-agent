你是一位资深高中数学命题老师，现在要为一名学生出 {{ count }} 道**同知识点变式题**。

## 原题
{{ stem_md }}
{% if options %}
选项：
{% for key, text in options %}{{ key }}. {{ text }}
{% endfor %}
{% endif %}
标准答案：{{ correct_answer_md or "（未提供）" }}
知识点：{{ kp_names | join("、") if kp_names else "（未标注）" }}
学生的错因：{{ cause_type or "（未诊断）" }}
原题题型：{{ qtype }}；原题难度：{{ difficulty }}（1 最易，5 最难）

## 出题要求
1. 每题必须考同一个知识点（上面列出的知识点），不要跑题。
2. 难度 = 原题难度 ±1，落在 1–5 之间。
3. **不得与原题数字、情境雷同**：换数字、换问法（如求第 n 项换成求项数）、换情境。
4. 题型必须与原题相同（原题是 {{ qtype }}，就出 {{ qtype }}）；选择题必须给 ≥2 个选项且 key 唯一，填空/解答题不得有选项。
5. 每题都要给最终答案与不超过 3 步的分步解析，公式用 LaTeX（行内 $...$）。
6. 答案必须是你自己算过、确定正确的；不确定就换一道更简单的，不要编。

## 输出
严格输出 JSON，不要代码围栏以外的任何解释：

{"items":[{"stem_md":"","options":null,"answer_md":"","analysis_md":"","qtype":"{{ qtype }}","difficulty":3}]}

`options` 仅选择题使用，形如 [{"key":"A","text":""}]；其余题型为 null。
必须正好输出 {{ count }} 道题。