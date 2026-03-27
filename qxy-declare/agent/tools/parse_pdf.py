#!/usr/bin/env python3
"""
parse_pdf — PDF 结构化识别（OCR + 数据提取）
输入: {"pdf_path": "/path/to/file.pdf"} 或 {"pdf_url": "https://..."}
输出: {"ok": true, "structured_data": {...}, "raw_text": "..."}
"""

import base64
from pathlib import Path
from shared import api_call, output, parse_args, log


def parse_pdf(pdf_path: str = None, pdf_url: str = None) -> dict:
    payload = {}

    if pdf_path:
        # 读取本地文件，转 base64 发送
        p = Path(pdf_path)
        if not p.exists():
            return {"ok": False, "error": f"文件不存在: {pdf_path}"}
        pdf_bytes = p.read_bytes()
        payload["pdf_data"] = base64.b64encode(pdf_bytes).decode()
        payload["filename"] = p.name
    elif pdf_url:
        payload["pdf_url"] = pdf_url
    else:
        return {"ok": False, "error": "需要提供 pdf_path 或 pdf_url"}

    result = api_call("parse_pdf", payload=payload)

    if not result["ok"]:
        return {
            "ok": False,
            "error": result["error"],
            "message": f"PDF 解析失败: {result['error']}",
        }

    data = result["data"]
    return {
        "ok": True,
        "structured_data": data.get("structured_data", data.get("result", {})),
        "raw_text": data.get("raw_text", data.get("text", "")),
        "confidence": data.get("confidence", None),
        "page_count": data.get("page_count", None),
    }


if __name__ == "__main__":
    args = parse_args()
    result = parse_pdf(
        pdf_path=args.get("pdf_path"),
        pdf_url=args.get("pdf_url"),
    )
    output(result)
