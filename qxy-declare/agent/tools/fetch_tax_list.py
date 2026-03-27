#!/usr/bin/env python3
"""
fetch_tax_list — 获取应申报清册
对应企享云接口:
  1. 发起: initiate_roster_entry (api-66960663)
  2. 轮询: query_task_info → business_status=3
"""

from shared import api_call, poll_task, output, parse_args, log


def fetch_tax_list(agg_org_id: str, year: int, period: int) -> dict:
    """
    获取企业本期应申报的税种清册
    Args:
        agg_org_id: 企业聚合ID
        year: 年份 (如 2026)
        period: 期间 (如 2 表示2月)
    """
    # 1. 发起获取申报条目任务
    result = api_call("initiate_roster_entry", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message", "发起获取清册失败")),
            "code": result.get("code"),
        }

    # 提取 taskId
    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))
    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    # 2. 轮询结果
    poll_result = poll_task(agg_org_id, task_id)

    if not poll_result["ok"]:
        return {
            "ok": False,
            "error": poll_result.get("error"),
            "status": poll_result.get("status"),
        }

    # 3. 解析清册数据
    roster_data = poll_result.get("data", {})
    biz_data = roster_data.get("data", roster_data)

    # 提取税种列表（字段名根据实际返回调整）
    items = biz_data.get("rosterEntries", biz_data.get("items",
            biz_data.get("list", biz_data.get("declareItems", []))))

    required = [
        item for item in items
        if item.get("declareStatus") not in ("已申报", "completed")
    ]

    return {
        "ok": True,
        "tax_items": items,
        "required_items": required,
        "has_required": len(required) > 0,
        "total_count": len(items),
        "required_count": len(required),
        "raw_data": biz_data,
    }


if __name__ == "__main__":
    args = parse_args()
    result = fetch_tax_list(
        agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
        year=int(args.get("year", 2026)),
        period=int(args.get("period", 1)),
    )
    output(result)
