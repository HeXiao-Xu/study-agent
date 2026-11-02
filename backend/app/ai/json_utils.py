"""结构化输出的宽松取 JSON：模型常把 JSON 包在 ```json 里或加解说词。

只做「定位第一个 { 到最后一个 }」这一件事，字段校验交给 Pydantic ——
解析层容错、校验层严格，两层职责不混。
"""
from __future__ import annotations

import json


def loads_json_object(text: str) -> dict:
    clean = (text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:]
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(clean[start : end + 1])
