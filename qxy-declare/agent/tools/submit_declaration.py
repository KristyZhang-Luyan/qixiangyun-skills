#!/usr/bin/env python3
"""
submit_declaration — 提交申报
对应企享云接口:
  方式1 (标准申报): upload_tax_report (api-67298736) → query_tax_report_result
  方式2 (简易申报): simplified_declare (api-209615709) → query_simplified_result
  方式3 (财报):    upload_financial_report (api-67585521) → query_financial_report_result
"""

from shared import api_call, poll_task, output, parse_args, log


def submit_standard(agg_org_id: str, year: int, period: int,
                    report_data: dict, direct_declare: bool = True) -> dict:
    """标准申报 — 上传申报数据"""
    payload = {
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "isDirectDeclare": direct_declare,
        **report_data,
    }

    result = api_call("upload_tax_report", payload=payload)

    if not result["ok"]:
        return _handle_error(result)

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    # 轮询结果
    poll_result = poll_task(agg_org_id, task_id,
                           result_endpoint="query_tax_report_result")

    return _format_result(poll_result, task_id, "standard")


def submit_simplified(agg_org_id: str, year: int, period: int,
                      sb_init: bool = False, issfqr: int = 0) -> dict:
    """
    简易申报（增值税小规模、增值税一般人、企业所得税）
    流程: 初始化(sbInit=Y) → 税费确认(issfqr=1) → 申报(issfqr=0)
    """
    # Step 1: 初始化
    if sb_init:
        result = api_call("simplified_declare", payload={
            "aggOrgId": agg_org_id,
            "year": year,
            "period": period,
            "sbInit": "Y",
        })
        if not result["ok"]:
            return _handle_error(result)

        data = result["data"]
        task_id = data.get("data", {}).get("taskId", data.get("taskId"))
        if task_id:
            poll_task(agg_org_id, task_id)

    # Step 2: 税费确认（判断是否可简易申报）
    if issfqr == 1:
        result = api_call("simplified_declare", payload={
            "aggOrgId": agg_org_id,
            "year": year,
            "period": period,
            "issfqr": 1,
        })
        if not result["ok"]:
            return _handle_error(result)

    # Step 3: 正式申报
    result = api_call("simplified_declare", payload={
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "issfqr": 0,
    })

    if not result["ok"]:
        return _handle_error(result)

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    poll_result = poll_task(agg_org_id, task_id,
                           result_endpoint="query_simplified_result")

    return _format_result(poll_result, task_id, "simplified")


def submit_financial_report(agg_org_id: str, year: int, period: int,
                            report_data: dict, direct_declare: bool = True) -> dict:
    """财报申报"""
    payload = {
        "aggOrgId": agg_org_id,
        "year": year,
        "period": period,
        "isDirectDeclare": direct_declare,
        **report_data,
    }

    result = api_call("upload_financial_report", payload=payload)

    if not result["ok"]:
        return _handle_error(result)

    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))

    if not task_id:
        return {"ok": False, "error": "未获取到 taskId", "raw": data}

    poll_result = poll_task(agg_org_id, task_id,
                           result_endpoint="query_financial_report_result")

    return _format_result(poll_result, task_id, "financial")


# ── 辅助函数 ─────────────────────────────────────────

ERROR_PATTERNS = {
    "system_unstable": ["服务不稳定", "暂时不可用", "繁忙", "系统异常", "核心征管", "超时"],
    "period_mismatch": ["所属期", "不一致"],
    "type_mismatch":   ["认定类型", "不一致"],
    "entry_not_found": ["无法选择", "无法找到", "入口"],
    "comparison_fail": ["比对不通过"],
    "already_declared": ["已申报", "重复申报"],
    "need_report_first": ["抄报税"],
    "previous_missing": ["上期未申报"],
    "cancelled":       ["注销"],
    "identity_error":  ["身份类型"],
    "login_expired":   ["登录信息已过期", "过期"],
    "account_locked":  ["锁定", "连续多次"],
}

def _classify_error(msg: str) -> str:
    """根据错误信息关键字分类"""
    for error_type, keywords in ERROR_PATTERNS.items():
        for kw in keywords:
            if kw in msg:
                return error_type
    return "unknown"

def _handle_error(result: dict) -> dict:
    code = str(result.get("code", ""))
    msg = result.get("message", result.get("error", ""))
    error_type = _classify_error(msg)

    retryable = error_type in ("system_unstable", "login_expired")

    return {
        "ok": False,
        "error": msg,
        "code": code,
        "error_type": error_type,
        "retryable": retryable,
        "message": msg,
    }

def _format_result(poll_result: dict, task_id, declare_type: str) -> dict:
    if poll_result["ok"] and poll_result.get("status") == "completed":
        data = poll_result.get("data", {})
        biz_data = data.get("data", data)

        return {
            "ok": True,
            "task_id": task_id,
            "declare_type": declare_type,
            "status": "success",
            "data": biz_data,
            "poll_attempts": poll_result.get("poll_attempts"),
            "message": "申报成功",
        }

    error = poll_result.get("error", "申报失败")
    return {
        "ok": False,
        "task_id": task_id,
        "declare_type": declare_type,
        "status": poll_result.get("status", "failed"),
        "error": error,
        "error_type": _classify_error(error),
        "retryable": _classify_error(error) in ("system_unstable",),
        "data": poll_result.get("data"),
    }


def batch_submit(companies: list, year: int, period: int) -> dict:
    """
    批量提交多个企业的申报
    Args:
        companies: [{
            "agg_org_id": "xxx",
            "company_name": "xxx",
            "mode": "standard" | "simplified" | "financial",
            "report_data": {...},  # standard/financial 需要
            "is_zero": False,      # simplified 判断依据
            "company_type": "small_scale",
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
        mode = company.get("mode", "standard")
        report_data = company.get("report_data", {})
        is_zero = company.get("is_zero", False)
        company_type = company.get("company_type", "small_scale")

        log.info(f"[批量申报] 开始处理: {company_name} ({agg_org_id}), 模式={mode}")

        try:
            if mode == "simplified" or (is_zero and company_type in ("small_scale", "general")):
                result = submit_simplified(agg_org_id, year, period, sb_init=True)
            elif mode == "financial":
                result = submit_financial_report(agg_org_id, year, period, report_data)
            else:
                result = submit_standard(agg_org_id, year, period, report_data)

            result["agg_org_id"] = agg_org_id
            result["company_name"] = company_name

            if result["ok"]:
                results.append(result)
                log.info(f"[批量申报] {company_name}: 申报成功")
            else:
                errors.append({
                    "agg_org_id": agg_org_id,
                    "company_name": company_name,
                    "error": result.get("error"),
                    "error_type": result.get("error_type"),
                    "retryable": result.get("retryable", False),
                    "code": result.get("code"),
                })
                log.error(f"[批量申报] {company_name}: 申报失败 - {result.get('error')}")

        except Exception as e:
            errors.append({
                "agg_org_id": agg_org_id,
                "company_name": company_name,
                "error": str(e),
                "error_type": "exception",
                "retryable": True,
            })
            log.error(f"[批量申报] {company_name}: 异常 - {e}")

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
    mode = args.get("mode", "standard")

    if mode == "batch":
        result = batch_submit(
            companies=args.get("companies", []),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
        )
    elif mode == "simplified":
        result = submit_simplified(agg_org_id, year, period,
                                   sb_init=args.get("sb_init", True),
                                   issfqr=args.get("issfqr", 0))
    elif mode == "financial":
        result = submit_financial_report(agg_org_id, year, period,
                                         report_data=args.get("report_data", {}))
    else:
        agg_org_id = str(args.get("agg_org_id", args.get("aggOrgId", "")))
        year = int(args.get("year", 2026))
        period = int(args.get("period", 1))
        result = submit_standard(agg_org_id, year, period,
                                 report_data=args.get("report_data", {}))
    output(result)
