#!/usr/bin/env python3
"""
init_declaration — 申报表数据初始化
对应企享云接口:
  1. 发起: load_init_data_task (api-69420373)
  2. 轮询: query_task_info
  3. 获取结果: get_init_data (api-69497719)
"""

from shared import api_call, output, parse_args, log


def init_declaration(agg_org_id: str, year: int, period: int,
                     tax_items: list) -> dict:
    """
    初始化各税种申报表，获取预填数据
    Args:
        agg_org_id: 企业聚合ID
        year: 年份
        period: 期间
        tax_items: 需要初始化的税种列表 (从 fetch_tax_list 的 required_items 来)
    """
    results = []
    errors = []

    # 计算所属期起止（增值税按月，企业所得税按季）
    def _compute_ssq(yzpzzl_dm, y, p):
        """根据税种代码计算所属期起止"""
        # 企业所得税（季报）：所属期为季度首日到季度末日
        if yzpzzl_dm in ("BDA0611159", "BDA0610100"):
            q_start_month = ((p - 1) // 3) * 3 + 1 if p > 0 else 1
            q_end_month = q_start_month + 2
            import calendar
            last_day = calendar.monthrange(y, q_end_month)[1]
            return f"{y}-{q_start_month:02d}-01", f"{y}-{q_end_month:02d}-{last_day}"
        # 增值税及其他：按月
        else:
            import calendar
            last_day = calendar.monthrange(y, p)[1]
            return f"{y}-{p:02d}-01", f"{y}-{p:02d}-{last_day}"

    for item in tax_items:
        yzpzzl_dm = item.get("yzpzzlDm", item.get("tax_code", ""))
        tax_name = item.get("zsxmMc", item.get("tax_name", yzpzzl_dm))

        log.info(f"初始化税种: {tax_name} ({yzpzzl_dm})")

        # 计算所属期
        ssq_q, ssq_z = _compute_ssq(yzpzzl_dm, year, period)

        # 1. 发起初始化任务 — 用 zsxmList 格式，ssqQ/ssqZ 放在每个项目内
        result = api_call("load_init_data_task", payload={
            "aggOrgId": agg_org_id,
            "year": year,
            "period": period,
            "zsxmList": [{
                "yzpzzlDm": yzpzzl_dm,
                "ssqQ": ssq_q,
                "ssqZ": ssq_z,
            }],
        })

        if not result["ok"]:
            code = result.get("code", "")
            msg = result.get("message", result.get("error", ""))

            # 已申报的跳过
            if "已申报" in msg:
                results.append({
                    "tax_code": yzpzzl_dm,
                    "tax_name": tax_name,
                    "status": "already_declared",
                    "message": msg,
                })
                continue

            errors.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "error": msg,
                "code": code,
            })
            continue

        # 2. 轮询获取初始化数据（initialize_data 服务无独立状态查询接口，
        #    直接用 get_init_data 轮询，返回有效数据即为成功）
        import time as _time
        poll_interval = 10
        poll_max = 30
        detail_data = None
        poll_ok = False
        last_error = ""

        not_found_count = 0

        for attempt in range(1, poll_max + 1):
            detail = api_call("get_init_data", payload={
                "aggOrgId": agg_org_id,
                "year": year,
                "period": period,
                "yzpzzlDm": yzpzzl_dm,
            })

            if detail["ok"]:
                detail_data = detail["data"]
                if not isinstance(detail_data, dict):
                    log.info(f"get_init_data 第 {attempt}/{poll_max} 次: 返回非dict，继续等待")
                    if attempt < poll_max:
                        _time.sleep(poll_interval)
                    continue

                msg = detail_data.get("message", "")
                inner_data = detail_data.get("data")
                raw = detail_data.get("raw_text", "")

                # "未找到初始化的任务" → 连续出现3次就放弃
                if "未找到" in msg:
                    not_found_count += 1
                    log.info(f"get_init_data 第 {attempt}/{poll_max} 次: {msg} (连续{not_found_count}次)")
                    if not_found_count >= 3:
                        last_error = msg
                        log.warning(f"get_init_data 连续{not_found_count}次未找到任务，放弃")
                        break
                # 任务还在执行中
                elif inner_data is None or "执行中" in msg:
                    not_found_count = 0
                    log.info(f"get_init_data 第 {attempt}/{poll_max} 次: {msg or '数据未就绪'}")
                elif raw:
                    not_found_count = 0
                    log.info(f"get_init_data 第 {attempt}/{poll_max} 次: 数据未就绪(raw_text)")
                else:
                    log.info(f"get_init_data 第 {attempt}/{poll_max} 次: 成功")
                    poll_ok = True
                    break
            else:
                last_error = detail.get("error", detail.get("message", ""))
                log.info(f"get_init_data 第 {attempt}/{poll_max} 次: {last_error}")

            if attempt < poll_max:
                _time.sleep(poll_interval)

        if poll_ok and detail_data:
            results.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "status": "initialized",
                "init_data": detail_data,
            })
        else:
            errors.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "error": last_error or f"轮询 {poll_max} 次后仍未获取到初始化数据",
                "status": "timeout",
            })

    return {
        "ok": len(errors) == 0,
        "results": results,
        "errors": errors,
        "initialized_count": len([r for r in results if r["status"] == "initialized"]),
        "error_count": len(errors),
    }


def batch_init_declaration(companies: list, year: int, period: int) -> dict:
    """
    批量初始化多个企业的申报表数据
    Args:
        companies: [{
            "agg_org_id": "xxx",
            "company_name": "xxx",
            "tax_items": [{"yzpzzlDm": "BDA0610606", ...}]
        }, ...]
        year: 年份
        period: 期间
    Returns:
        {"ok": bool, "results": [...], "errors": [...]}
    """
    all_results = []
    all_errors = []

    for company in companies:
        agg_org_id = str(company.get("agg_org_id", company.get("aggOrgId", "")))
        company_name = company.get("company_name", agg_org_id)
        tax_items = company.get("tax_items", [])

        log.info(f"[批量初始化] 开始处理: {company_name} ({agg_org_id}), {len(tax_items)} 个税种")

        result = init_declaration(agg_org_id, year, period, tax_items)
        result["agg_org_id"] = agg_org_id
        result["company_name"] = company_name

        if result["ok"]:
            all_results.append(result)
            log.info(f"[批量初始化] {company_name}: 成功初始化 {result.get('initialized_count', 0)} 个税种")
        else:
            all_errors.append({
                "agg_org_id": agg_org_id,
                "company_name": company_name,
                "errors": result.get("errors", []),
            })
            log.error(f"[批量初始化] {company_name}: 初始化失败")

    return {
        "ok": len(all_errors) == 0,
        "results": all_results,
        "errors": all_errors,
        "total_companies": len(companies),
        "success_count": len(all_results),
        "error_count": len(all_errors),
    }


if __name__ == "__main__":
    args = parse_args()
    mode = args.get("mode", "single")

    if mode == "batch":
        result = batch_init_declaration(
            companies=args.get("companies", []),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
        )
    else:
        result = init_declaration(
            agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
            year=int(args.get("year", 2026)),
            period=int(args.get("period", 1)),
            tax_items=args.get("tax_items", []),
        )
    output(result)