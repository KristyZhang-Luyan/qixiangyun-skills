#!/usr/bin/env python3
"""
download_receipt — 下载申报 PDF 回执
对应企享云接口:
  1. 发起: load_pdf_task (api-67645165)
  2. 轮询: query_task_info
  3. 结果: query_pdf_result (api-212658227) 返回结构化数据
"""

from shared import api_call, poll_task, output, parse_args, log


def download_receipt(agg_org_id: str, year: int, period: int,
                     zsxm_list: list) -> dict:
    """
    下载当期 PDF 并获取结构化数据
    Args:
        agg_org_id: 企业聚合ID
        year: 年份
        period: 期间
        zsxm_list: 税种列表 [{"yzpzzlDm": "BDA0610606", ...}]
    """
    # 1. 发起下载 PDF 任务
    result = api_call("load_pdf_task", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "zsxmList": zsxm_list,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message")),
            "retryable": True,
        }

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    # 2. 轮询任务完成
    poll_result = poll_task(agg_org_id, task_id)

    if not poll_result["ok"]:
        return {
            "ok": False,
            "error": poll_result.get("error"),
            "status": poll_result.get("status"),
            "retryable": poll_result.get("status") != "failed",
        }

    # 3. 查询 PDF 结构化数据
    pdf_detail = api_call("query_pdf_result", payload={
        "aggOrgId": agg_org_id,
        "taskId": task_id,
    })

    result_data = poll_result.get("data", {})
    biz_data = result_data.get("data", result_data)

    return {
        "ok": True,
        "task_id": task_id,
        "pdf_data": biz_data,
        "structured_data": pdf_detail.get("data") if pdf_detail.get("ok") else None,
        "message": "PDF 下载完成",
    }


if __name__ == "__main__":
    args = parse_args()
    result = download_receipt(
        agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
        year=int(args.get("year", 2026)),
        period=int(args.get("period", 1)),
        zsxm_list=args.get("zsxm_list", args.get("zsxmList", [])),
    )
    output(result)
