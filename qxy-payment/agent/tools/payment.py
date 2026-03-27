#!/usr/bin/env python3
"""
payment — 税款缴纳 & 完税证明
对应企享云接口:
  缴款: load_payment_task → 轮询 query_task_info（默认三方协议直接扣款）
  完税证明: load_wszm_task → 轮询 query_wszm_result
"""

from shared import api_call, poll_task, output, parse_args, log


def execute_payment(agg_org_id: str, year: int, period: int,
                    payment_detail: list = None) -> dict:
    """
    发起税款缴纳（默认三方协议直接银行扣款）
    """
    payload = {
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
    }
    if payment_detail:
        payload["detail"] = payment_detail

    result = api_call("load_payment_task", payload=payload)

    if not result["ok"]:
        error_msg = result.get("error", result.get("message", "发起缴款失败"))
        retryable = "超时" in error_msg or "网络" in error_msg or result.get("code", 0) >= 500
        return {
            "ok": False,
            "error": error_msg,
            "code": result.get("code"),
            "retryable": retryable,
        }

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    poll_result = poll_task(agg_org_id, task_id)

    if poll_result["ok"] and poll_result.get("status") == "completed":
        biz_data = poll_result.get("data", {}).get("data", poll_result.get("data", {}))
        return {
            "ok": True,
            "task_id": task_id,
            "status": "success",
            "data": biz_data,
            "message": "缴款成功",
        }

    return {
        "ok": False,
        "task_id": task_id,
        "status": poll_result.get("status", "failed"),
        "error": poll_result.get("error", "缴款失败"),
        "data": poll_result.get("data"),
        "retryable": poll_result.get("status") != "failed",
    }


def download_tax_certificate(agg_org_id: str, year: int, period: int,
                             zsxm_list: list = None) -> dict:
    """下载完税证明 PDF"""
    payload = {
        "aggOrgId": agg_org_id,
    }
    if zsxm_list:
        payload["zsxmDtos"] = zsxm_list

    result = api_call("load_wszm_task", payload=payload)

    if not result["ok"]:
        return {"ok": False, "error": result.get("error", "发起完税证明下载失败")}

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId"}

    poll_result = poll_task(agg_org_id, task_id, result_endpoint="query_wszm_result")

    if poll_result["ok"]:
        return {
            "ok": True,
            "task_id": task_id,
            "status": "completed",
            "data": poll_result.get("data"),
            "message": "完税证明下载完成",
        }

    return {
        "ok": False,
        "task_id": task_id,
        "status": poll_result.get("status"),
        "error": poll_result.get("error", "完税证明下载失败"),
    }


if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "pay")

    if action == "certificate":
        result = download_tax_certificate(
            agg_org_id=str(args.get("agg_org_id", "")),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
            zsxm_list=args.get("zsxm_list", []),
        )
    else:
        result = execute_payment(
            agg_org_id=str(args.get("agg_org_id", "")),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
            payment_detail=args.get("detail", []),
        )
    output(result)