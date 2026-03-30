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
    # 补充 ssqQ/ssqZ（如果调用方没有传入）
    import calendar
    last_day = calendar.monthrange(year, period)[1]
    default_ssqQ = f"{year}-{period:02d}-01"
    default_ssqZ = f"{year}-{period:02d}-{last_day}"

    full_zsxm_list = []
    for item in zsxm_list:
        full_item = dict(item)
        if "ssqQ" not in full_item:
            full_item["ssqQ"] = default_ssqQ
        if "ssqZ" not in full_item:
            full_item["ssqZ"] = default_ssqZ
        full_zsxm_list.append(full_item)

    result = api_call("load_pdf_task", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "zsxmList": full_zsxm_list,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message")),
            "retryable": True,
        }

    data = result["data"]
    task_id = (data.get("data") or {}).get("taskId", data.get("taskId"))

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


def batch_download_receipt(companies: list, year: int, period: int) -> dict:
    """
    批量下载多个企业的申报 PDF 回执
    Args:
        companies: [{
            "agg_org_id": "xxx",
            "company_name": "xxx",
            "zsxm_list": [{"yzpzzlDm": "BDA0610606"}]
        }, ...]
        year: 年份
        period: 期间
    Returns:
        {"ok": bool, "results": [...], "errors": [...]}
    """
    results = []
    errors = []

    for company in companies:
        agg_org_id = str(company.get("agg_org_id", company.get("aggOrgId", "")))
        company_name = company.get("company_name", agg_org_id)
        zsxm_list = company.get("zsxm_list", company.get("zsxmList", []))

        log.info(f"[批量下载PDF] 开始处理: {company_name} ({agg_org_id})")

        result = download_receipt(agg_org_id, year, period, zsxm_list)
        result["agg_org_id"] = agg_org_id
        result["company_name"] = company_name

        if result["ok"]:
            results.append(result)
            log.info(f"[批量下载PDF] {company_name}: 下载成功")
        else:
            errors.append({
                "agg_org_id": agg_org_id,
                "company_name": company_name,
                "error": result.get("error"),
                "retryable": result.get("retryable", False),
            })
            log.error(f"[批量下载PDF] {company_name}: 下载失败 - {result.get('error')}")

    return {
        "ok": len(errors) == 0,
        "results": results,
        "errors": errors,
        "total_companies": len(companies),
        "success_count": len(results),
        "error_count": len(errors),
    }


if __name__ == "__main__":
    args = parse_args()
    mode = args.get("mode", "single")

    if mode == "batch":
        result = batch_download_receipt(
            companies=args.get("companies", []),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
        )
    else:
        result = download_receipt(
            agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
            zsxm_list=args.get("zsxm_list", args.get("zsxmList", [])),
        )
    output(result)