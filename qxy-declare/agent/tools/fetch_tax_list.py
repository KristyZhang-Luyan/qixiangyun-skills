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
    log.info(f"[获取清册] 发起请求: aggOrgId={agg_org_id}, year={year}, period={period}")
    result = api_call("initiate_roster_entry", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
    })

    if not result["ok"]:
        log.error(f"[获取清册] 发起失败: {result.get('error')} code={result.get('code')}")
        return {
            "ok": False,
            "error": result.get("error", result.get("message", "发起获取清册失败")),
            "code": result.get("code"),
        }

    # 提取 taskId
    data = result["data"]
    task_id = (data.get("data") or {}).get("taskId", data.get("taskId"))
    if not task_id:
        log.error(f"[获取清册] 未获取到 taskId, 原始返回: {data}")
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    log.info(f"[获取清册] 获取到 taskId={task_id}，开始轮询...")

    # 2. 轮询结果
    poll_result = poll_task(agg_org_id, task_id)

    if not poll_result["ok"]:
        log.error(f"[获取清册] 轮询失败: status={poll_result.get('status')} error={poll_result.get('error')} taskId={task_id} attempts={poll_result.get('poll_attempts')}")
        return {
            "ok": False,
            "error": poll_result.get("error"),
            "status": poll_result.get("status"),
            "task_id": task_id,
        }

    # 3. 解析清册数据
    roster_data = poll_result.get("data", {})
    biz_data = roster_data.get("data", roster_data)

    # 提取税种列表 — 实际返回字段名为 detail
    items = biz_data.get("detail", biz_data.get("rosterEntries", biz_data.get("items",
            biz_data.get("list", biz_data.get("declareItems", [])))))

    # ── 税种白名单：当前只处理增值税和企业所得税 ──
    SUPPORTED_TAX_CODES = {
        "BDA0610606",  # 增值税及附加税费（小规模纳税人）
        "BDA0620200",  # 增值税及附加税费（小规模-其他）
        "BDA0610600",  # 增值税（一般纳税人）
        "BDA0610601",  # 增值税（一般纳税人-其他）
        "BDA0611159",  # 企业所得税A类（季报）
        "BDA0610100",  # 企业所得税B类（季报）
        "BDA0610101",  # 企业所得税（其他）
        "CWBBSB",      # 财务报表（月/季报）
        "CWBBNDSB",    # 财务报表（年报）
    }

    # 过滤需要申报的：
    #   - 只保留白名单内的税种（增值税、企业所得税、财务报表）
    #   - code=2000 且 state 不为 "1"(已申报) 的视为待申报
    #   - 没有 state 字段的默认为待申报
    required = []
    skipped_codes = []
    for item in items:
        code = str(item.get("code", ""))
        state = str(item.get("state", ""))
        declare_status = item.get("declareStatus", "")
        yzpzzl_dm = item.get("yzpzzlDm", "")

        # 跳过不在白名单内的税种
        if yzpzzl_dm and yzpzzl_dm not in SUPPORTED_TAX_CODES:
            skipped_codes.append(f"{item.get('zsxmMc', yzpzzl_dm)}({yzpzzl_dm})")
            continue
        # 跳过已申报的
        if declare_status in ("已申报", "completed") or state == "1":
            continue
        # 跳过失败的
        if code not in ("2000", "SUCCESS", ""):
            continue
        required.append(item)

    if skipped_codes:
        log.info(f"跳过不支持的税种: {', '.join(skipped_codes)}")

    return {
        "ok": True,
        "tax_items": items,
        "required_items": required,
        "has_required": len(required) > 0,
        "total_count": len(items),
        "required_count": len(required),
        "raw_data": biz_data,
    }


def batch_fetch_tax_list(companies: list, year: int, period: int) -> dict:
    """
    批量获取多个企业的应申报清册
    Args:
        companies: [{"agg_org_id": "xxx", "company_name": "xxx", "company_id": "xxx"}, ...]
        year: 年份
        period: 期间
    Returns:
        {"ok": bool, "results": [...], "errors": [...], "summary": {...}}
    """
    results = []
    errors = []

    for company in companies:
        agg_org_id = str(company.get("agg_org_id", company.get("aggOrgId", "")))
        company_name = company.get("company_name", agg_org_id)
        company_id = company.get("company_id", "")

        log.info(f"[批量获取清册] 开始处理: {company_name} ({agg_org_id})")

        result = fetch_tax_list(agg_org_id, year, period)
        result["agg_org_id"] = agg_org_id
        result["company_name"] = company_name
        result["company_id"] = company_id

        if result["ok"]:
            results.append(result)
            log.info(f"[批量获取清册] {company_name}: 需申报 {result.get('required_count', 0)} 个税种")
        else:
            errors.append({
                "agg_org_id": agg_org_id,
                "company_name": company_name,
                "company_id": company_id,
                "error": result.get("error"),
                "code": result.get("code"),
            })
            log.error(f"[批量获取清册] {company_name} 失败: {result.get('error')}")

    return {
        "ok": len(errors) == 0,
        "results": results,
        "errors": errors,
        "total_companies": len(companies),
        "success_count": len(results),
        "error_count": len(errors),
        "summary": {
            "total_required_items": sum(r.get("required_count", 0) for r in results),
        },
    }


if __name__ == "__main__":
    args = parse_args()
    mode = args.get("mode", "single")

    if mode == "batch":
        result = batch_fetch_tax_list(
            companies=args.get("companies", []),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
        )
    else:
        result = fetch_tax_list(
            agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
        )
    output(result)