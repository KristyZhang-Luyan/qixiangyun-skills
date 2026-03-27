#!/usr/bin/env python3
"""
init_declaration — 申报表数据初始化
对应企享云接口:
  1. 发起: load_init_data_task (api-69420373)
  2. 轮询: query_task_info
  3. 获取结果: get_init_data (api-69497719)
"""

from shared import api_call, poll_task, output, parse_args, log


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

    for item in tax_items:
        yzpzzl_dm = item.get("yzpzzlDm", item.get("tax_code", ""))
        tax_name = item.get("zsxmMc", item.get("tax_name", yzpzzl_dm))

        log.info(f"初始化税种: {tax_name} ({yzpzzl_dm})")

        # 1. 发起初始化任务
        result = api_call("load_init_data_task", payload={
            "aggOrgId": agg_org_id,
            "year": year,
            "period": period,
            "yzpzzlDm": yzpzzl_dm,
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

        data = result["data"]
        task_id = data.get("data", {}).get("taskId", data.get("taskId"))

        if not task_id:
            errors.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "error": "未获取到 taskId",
            })
            continue

        # 2. 轮询任务完成
        poll_result = poll_task(agg_org_id, task_id)

        if not poll_result["ok"]:
            errors.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "error": poll_result.get("error"),
                "status": poll_result.get("status"),
            })
            continue

        # 3. 获取初始化数据详情
        detail = api_call("get_init_data", payload={
            "aggOrgId": agg_org_id,
            "year": year,
            "period": period,
            "yzpzzlDm": yzpzzl_dm,
        })

        if detail["ok"]:
            results.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "status": "initialized",
                "init_data": detail["data"],
            })
        else:
            results.append({
                "tax_code": yzpzzl_dm,
                "tax_name": tax_name,
                "status": "initialized_no_detail",
                "init_data": poll_result.get("data"),
                "detail_error": detail.get("error"),
            })

    return {
        "ok": len(errors) == 0,
        "results": results,
        "errors": errors,
        "initialized_count": len([r for r in results if r["status"] == "initialized"]),
        "error_count": len(errors),
    }


if __name__ == "__main__":
    args = parse_args()
    result = init_declaration(
        agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
        year=int(args.get("year", 2026)),
        period=int(args.get("period", 1)),
        tax_items=args.get("tax_items", []),
    )
    output(result)
