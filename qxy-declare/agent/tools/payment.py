#!/usr/bin/env python3
"""
payment — 税款缴纳
对应企享云接口:
  1. 发起: load_payment_task (api-67662292)
  2. 轮询: query_task_info (api-67976986)
"""

from shared import api_call, poll_task, output, parse_args, log


def execute_payment(agg_org_id: str, year: int, period: int,
                    payment_detail: list) -> dict:
    """
    发起税款缴纳
    Args:
        agg_org_id: 企业聚合ID
        year: 年份
        period: 期间
        payment_detail: 缴款明细 [{"fromOrgId": "xxx", ...}]
    """
    result = api_call("load_payment_task", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "detail": payment_detail,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message")),
            "code": result.get("code"),
        }

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    # 轮询缴款结果
    poll_result = poll_task(agg_org_id, task_id)

    if poll_result["ok"] and poll_result.get("status") == "completed":
        return {
            "ok": True,
            "task_id": task_id,
            "status": "success",
            "data": poll_result.get("data"),
            "message": "缴款成功",
        }

    return {
        "ok": False,
        "task_id": task_id,
        "status": poll_result.get("status", "failed"),
        "error": poll_result.get("error"),
        "data": poll_result.get("data"),
    }


def download_tax_certificate(agg_org_id: str, zsxm_dtos: list) -> dict:
    """下载完税证明"""
    result = api_call("load_wszm_task", payload={
        "aggOrgId": agg_org_id,
        "zsxmDtos": zsxm_dtos,
    })

    if not result["ok"]:
        return {"ok": False, "error": result.get("error")}

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId"}

    poll_result = poll_task(agg_org_id, task_id,
                           result_endpoint="query_wszm_result")

    return {
        "ok": poll_result.get("ok", False),
        "task_id": task_id,
        "status": poll_result.get("status"),
        "data": poll_result.get("data"),
    }


if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "pay")

    if action == "certificate":
        result = download_tax_certificate(
            agg_org_id=str(args.get("agg_org_id", "")),
            zsxm_dtos=args.get("zsxm_dtos", []),
        )
    else:
        result = execute_payment(
            agg_org_id=str(args.get("agg_org_id", "")),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
            payment_detail=args.get("detail", []),
        )
    output(result)
