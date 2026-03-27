#!/usr/bin/env python3
"""
query_policy_kb — 查询优惠政策知识库

返回候选政策列表，由 LLM Agent 做最终匹配判断。
本脚本只负责检索，不做决策。

输入: {
    "company_id": "xxx",
    "company_type": "small_scale",
    "industry": "信息技术",
    "tax_codes": ["VAT", "CIT"],
    "period": "2026-02"
}
输出: {"ok": true, "policies": [...]}
"""

from shared import api_call, output, parse_args, log


def query_policy_kb(company_id: str, company_type: str, industry: str,
                    tax_codes: list, period: str) -> dict:
    result = api_call("query_policy", payload={
        "company_id": company_id,
        "company_type": company_type,
        "industry": industry,
        "tax_codes": tax_codes,
        "period": period,
    })

    if not result["ok"]:
        # 政策查询失败不阻断流程，返回空列表
        log.warning(f"政策知识库查询失败: {result['error']}，将跳过优惠匹配")
        return {
            "ok": True,  # 不阻断
            "policies": [],
            "query_failed": True,
            "message": f"政策知识库暂不可用: {result['error']}，可继续申报",
        }

    data = result["data"]
    policies = data.get("policies", data.get("items", []))

    return {
        "ok": True,
        "policies": policies,
        "policy_count": len(policies),
        "query_failed": False,
        "message": f"找到 {len(policies)} 条可能适用的优惠政策" if policies else "未找到适用的优惠政策",
    }


if __name__ == "__main__":
    args = parse_args()
    result = query_policy_kb(
        company_id=args.get("company_id", ""),
        company_type=args.get("company_type", ""),
        industry=args.get("industry", ""),
        tax_codes=args.get("tax_codes", []),
        period=args.get("period", ""),
    )
    output(result)
