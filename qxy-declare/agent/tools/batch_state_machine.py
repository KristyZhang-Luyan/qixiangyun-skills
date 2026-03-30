#!/usr/bin/env python3
"""
batch_state_machine.py — 批量申报状态机

用于同时处理多个企业的同一税种申报（如增值税批量申报）。
与单企业 state_machine.py 并行存在，不修改原有逻辑。

批量流程（对照 Excel 演示流程）：
  BATCH_INIT
    → BATCH_FETCH_LIST     (批量获取清册)
    → BATCH_NOTIFY_TAXES   (展示全部企业清册，等用户确认)
    → BATCH_DATA_INIT      (批量初始化申报数据)
    → BATCH_CONFIRM_TAX    (展示全部企业税额，等用户确认)
    → BATCH_SUBMIT         (批量提交申报)
    → BATCH_DOWNLOAD       (批量下载 PDF)
    → BATCH_NOTIFY_COMPLETE(通知用户，等确认)
    → BATCH_DONE

规则：
  1. advance() 每次只执行一步
  2. input 类型状态需要外部 inject
  3. blocked 就是停，等交互
  4. inject 必须带 user_said
"""

import json
from shared import (
    load_state, save_state, transition, fail,
    list_tasks, output, parse_args, log, now_iso,
    STATE_DIR,
)
from pathlib import Path
from fetch_tax_list import batch_fetch_tax_list
from init_declaration import batch_init_declaration
from submit_declaration import batch_submit
from download_receipt import batch_download_receipt


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 批量任务创建（独立于单企业 create_task）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_batch_task(companies: list, period: str,
                      tax_type: str = "vat",
                      batch_name: str = "") -> dict:
    """
    创建批量申报任务
    Args:
        companies: [{
            "company_id": "QXY100031100000001",
            "company_name": "测试企业1",
            "agg_org_id": "5208291448799296",
        }, ...]
        period: "2026-03"
        tax_type: "vat" (增值税) | "cit" (企业所得税)
        batch_name: 批次名称（可选）
    """
    batch_id = f"batch_{period.replace('-', '')}_{tax_type}_{now_iso()[:10].replace('-', '')}"
    if not batch_name:
        batch_name = f"{period} 批量{_tax_type_name(tax_type)}申报"

    state = {
        "task_id": batch_id,
        "batch_name": batch_name,
        "tax_type": tax_type,
        "period": period,
        "companies": companies,
        "company_count": len(companies),
        "state": "BATCH_INIT",
        "state_history": [],
        "data": {
            "fetch_list_result": None,
            "init_result": None,
            "submit_result": None,
            "download_result": None,
        },
        "interactions": {},
        "retry_count": 0,
        "max_retries": 3,
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }

    _save_batch_state(batch_id, state)
    log.info(f"[{batch_id}] 批量任务已创建: {len(companies)} 个企业, 税种={tax_type}")
    return state


def _tax_type_name(tax_type: str) -> str:
    return {"vat": "增值税", "cit": "企业所得税", "financial": "财报"}.get(tax_type, tax_type)


def _tax_type_code(tax_type: str) -> str:
    return {
        "vat": "BDA0610606",
        "cit": "BDA0611159",
    }.get(tax_type, "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 批量状态定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BATCH_STATE_DEFS = {
    "BATCH_INIT": {
        "type": "auto",
        "handler": "do_batch_init",
    },
    "BATCH_FETCH_LIST": {
        "type": "auto",
        "handler": "do_batch_fetch_list",
    },
    "BATCH_NOTIFY_TAXES": {
        "type": "input",
        "required_input": "batch_notify_ack",
        "handler": "do_batch_notify_taxes",
        "message": (
            "【必须和用户交互】请向用户展示所有企业的申报清册汇总，等用户确认后 inject:\n"
            'data_key="batch_notify_ack" data_value={"user_said": "用户的原话"}'
        ),
    },
    "BATCH_DATA_INIT": {
        "type": "auto",
        "handler": "do_batch_data_init",
    },
    "BATCH_CONFIRM_TAX": {
        "type": "input",
        "required_input": "batch_tax_confirm",
        "handler": "do_batch_confirm_tax",
        "message": (
            "【必须和用户交互】请向用户展示所有企业的初始化数据/税额，等用户确认后 inject:\n"
            'data_key="batch_tax_confirm" data_value={"user_said": "用户的原话"}'
        ),
    },
    "BATCH_SUBMIT": {
        "type": "auto",
        "handler": "do_batch_submit",
    },
    "BATCH_DOWNLOAD": {
        "type": "auto",
        "handler": "do_batch_download",
    },
    "BATCH_NOTIFY_COMPLETE": {
        "type": "input",
        "required_input": "batch_complete_ack",
        "handler": "do_batch_notify_complete",
        "message": (
            "【必须和用户交互】请向用户发送批量申报完成汇总（各企业税额），\n"
            "用户确认收到后 inject:\n"
            'data_key="batch_complete_ack" data_value={"user_said": "用户的原话"}'
        ),
    },
    "BATCH_DONE": {
        "type": "terminal",
        "handler": "do_batch_done",
    },
    "BATCH_FAILED": {
        "type": "terminal",
        "handler": "do_batch_failed",
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 批量状态处理函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _parse_period(p: str) -> tuple:
    parts = p.split("-")
    return int(parts[0]), int(parts[1])


def do_batch_init(state: dict) -> dict:
    companies = state.get("companies", [])
    if not companies:
        return {"blocked": True, "error": "企业列表为空"}

    missing = [c for c in companies if not c.get("agg_org_id")]
    if missing:
        names = [c.get("company_name", "?") for c in missing]
        return {"blocked": True, "error": f"以下企业缺少 agg_org_id: {', '.join(names)}"}

    log.info(f"[{state['task_id']}] BATCH_INIT: {len(companies)} 个企业待处理")
    return {"next": "BATCH_FETCH_LIST"}


def do_batch_fetch_list(state: dict) -> dict:
    year, period = _parse_period(state["period"])
    companies = state["companies"]

    result = batch_fetch_tax_list(companies, year, period)
    state["data"]["fetch_list_result"] = result
    _save_batch_state(state["task_id"], state)

    if result["error_count"] > 0:
        failed_names = [e.get("company_name", "") for e in result.get("errors", [])]
        fail(state, f"获取清册失败: {', '.join(failed_names)}")
        return {"next": "BATCH_FAILED"}

    return {"next": "BATCH_NOTIFY_TAXES"}


def do_batch_notify_taxes(state: dict) -> dict:
    return {"next": "BATCH_DATA_INIT"}


def do_batch_data_init(state: dict) -> dict:
    year, period = _parse_period(state["period"])
    tax_type = state.get("tax_type", "vat")
    tax_code = _tax_type_code(tax_type)
    fetch_result = state["data"].get("fetch_list_result", {})
    fetch_results = fetch_result.get("results", [])

    # 为每个成功获取清册的企业，提取对应税种的 tax_items
    init_companies = []
    for fr in fetch_results:
        agg_org_id = fr.get("agg_org_id", "")
        company_name = fr.get("company_name", "")
        required_items = fr.get("required_items", [])

        # 筛选出目标税种
        if tax_code:
            target_items = [it for it in required_items if it.get("yzpzzlDm") == tax_code]
        else:
            target_items = required_items

        if target_items:
            init_companies.append({
                "agg_org_id": agg_org_id,
                "company_name": company_name,
                "tax_items": target_items,
            })

    if not init_companies:
        log.info(f"[{state['task_id']}] 无需初始化（所有企业该税种已申报或不在清册中）")
        state["data"]["init_result"] = {"ok": True, "results": [], "note": "无需初始化"}
        _save_batch_state(state["task_id"], state)
        return {"next": "BATCH_DONE"}

    result = batch_init_declaration(init_companies, year, period)
    state["data"]["init_result"] = result
    _save_batch_state(state["task_id"], state)

    if result["error_count"] > 0:
        failed_names = [e.get("company_name", "") for e in result.get("errors", [])]
        fail(state, f"初始化失败: {', '.join(failed_names)}")
        return {"next": "BATCH_FAILED"}

    return {"next": "BATCH_CONFIRM_TAX"}


def do_batch_confirm_tax(state: dict) -> dict:
    return {"next": "BATCH_SUBMIT"}


def do_batch_submit(state: dict) -> dict:
    year, period = _parse_period(state["period"])
    tax_type = state.get("tax_type", "vat")
    init_result = state["data"].get("init_result", {})
    init_results = init_result.get("results", [])

    submit_companies = []
    for ir in init_results:
        agg_org_id = ir.get("agg_org_id", "")
        company_name = ir.get("company_name", "")
        tax_results = ir.get("results", [])

        # 跳过已申报的
        to_submit = [r for r in tax_results if r.get("status") == "initialized"]
        already_declared = [r for r in tax_results if r.get("status") == "already_declared"]

        if already_declared and not to_submit:
            log.info(f"[{state['task_id']}] {company_name}: 已申报，跳过")
            continue

        # 判断是否零申报
        init_data = {}
        for r in to_submit:
            if r.get("init_data"):
                init_data = r["init_data"]
                break

        is_zero = _check_is_zero(init_data)

        submit_companies.append({
            "agg_org_id": agg_org_id,
            "company_name": company_name,
            "mode": "simplified" if is_zero else "standard",
            "is_zero": is_zero,
            "report_data": _build_report_data(init_data, tax_type),
            "company_type": "small_scale",
        })

    if not submit_companies:
        log.info(f"[{state['task_id']}] 无需提交申报（全部已申报或无数据）")
        state["data"]["submit_result"] = {"ok": True, "results": [], "note": "无需申报"}
        _save_batch_state(state["task_id"], state)
        return {"next": "BATCH_DOWNLOAD"}

    result = batch_submit(submit_companies, year, period)
    state["data"]["submit_result"] = result
    _save_batch_state(state["task_id"], state)

    if result["error_count"] > 0:
        failed_names = [e.get("company_name", "") for e in result.get("errors", [])]
        fail(state, f"申报失败: {', '.join(failed_names)}")
        return {"next": "BATCH_FAILED"}

    return {"next": "BATCH_DOWNLOAD"}


def _check_is_zero(init_data: dict) -> bool:
    if not init_data:
        return True
    data = init_data.get("data", init_data)
    if isinstance(data, dict):
        zbgrid = data.get("zbGrid", data.get("zbgrid", []))
        if isinstance(zbgrid, list):
            for row in zbgrid:
                for key in ("xxse", "jxse", "bqybtse", "ynsehj"):
                    val = row.get(key)
                    if val and float(val or 0) != 0:
                        return False
    return True


def _build_report_data(init_data: dict, tax_type: str) -> dict:
    if not init_data:
        return {}
    if tax_type == "vat":
        return {"ybData": init_data.get("data", init_data)}
    elif tax_type == "cit":
        return {"sdsData": init_data.get("data", init_data)}
    return init_data


def do_batch_download(state: dict) -> dict:
    year, period = _parse_period(state["period"])
    tax_type = state.get("tax_type", "vat")
    tax_code = _tax_type_code(tax_type)
    submit_result = state["data"].get("submit_result", {})
    submit_results = submit_result.get("results", [])

    import calendar
    last_day = calendar.monthrange(year, period)[1]
    default_ssqQ = f"{year}-{period:02d}-01"
    default_ssqZ = f"{year}-{period:02d}-{last_day}"

    download_companies = []
    for sr in submit_results:
        agg_org_id = sr.get("agg_org_id", "")
        company_name = sr.get("company_name", "")

        download_companies.append({
            "agg_org_id": agg_org_id,
            "company_name": company_name,
            "zsxm_list": [{"yzpzzlDm": tax_code, "ssqQ": default_ssqQ, "ssqZ": default_ssqZ}] if tax_code else [],
        })

    if not download_companies:
        state["data"]["download_result"] = {"ok": True, "results": [], "note": "无需下载"}
        _save_batch_state(state["task_id"], state)
        return {"next": "BATCH_NOTIFY_COMPLETE"}

    result = batch_download_receipt(download_companies, year, period)
    state["data"]["download_result"] = result
    _save_batch_state(state["task_id"], state)

    if result["error_count"] > 0:
        failed_names = [e.get("company_name", "") for e in result.get("errors", [])]
        fail(state, f"PDF下载失败: {', '.join(failed_names)}")
        return {"next": "BATCH_FAILED"}

    return {"next": "BATCH_NOTIFY_COMPLETE"}


def do_batch_notify_complete(state: dict) -> dict:
    return {"next": "BATCH_DONE"}


def do_batch_done(state: dict) -> dict:
    submit_result = state["data"].get("submit_result", {})
    submit_results = submit_result.get("results", [])

    company_summaries = []
    for sr in submit_results:
        company_summaries.append({
            "company_name": sr.get("company_name", ""),
            "agg_org_id": sr.get("agg_org_id", ""),
            "status": "success",
            "tax_amount": sr.get("data", {}).get("taxAmount", 0),
        })

    return {
        "terminal": True,
        "summary": {
            "task_id": state["task_id"],
            "batch_name": state["batch_name"],
            "period": state["period"],
            "tax_type": state["tax_type"],
            "status": "completed",
            "total_companies": state["company_count"],
            "success_count": len(submit_results),
            "error_count": 0,
            "company_summaries": company_summaries,
            "message": (
                f"{state['batch_name']}完成！"
                f"共 {state['company_count']} 家企业全部申报成功。"
            ),
        },
    }


def do_batch_failed(state: dict) -> dict:
    return {
        "terminal": True,
        "summary": {
            "task_id": state["task_id"],
            "batch_name": state["batch_name"],
            "period": state["period"],
            "tax_type": state["tax_type"],
            "status": "failed",
            "error": state.get("error"),
        },
    }


BATCH_HANDLER_MAP = {
    "do_batch_init": do_batch_init,
    "do_batch_fetch_list": do_batch_fetch_list,
    "do_batch_notify_taxes": do_batch_notify_taxes,
    "do_batch_data_init": do_batch_data_init,
    "do_batch_confirm_tax": do_batch_confirm_tax,
    "do_batch_submit": do_batch_submit,
    "do_batch_download": do_batch_download,
    "do_batch_notify_complete": do_batch_notify_complete,
    "do_batch_done": do_batch_done,
    "do_batch_failed": do_batch_failed,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 批量状态链路
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BATCH_STATE_CHAIN = [
    "BATCH_INIT",
    "BATCH_FETCH_LIST",
    "BATCH_NOTIFY_TAXES",
    "BATCH_DATA_INIT",
    "BATCH_CONFIRM_TAX",
    "BATCH_SUBMIT",
    "BATCH_DOWNLOAD",
    "BATCH_NOTIFY_COMPLETE",
    "BATCH_DONE",
]

BATCH_STATE_EVIDENCE = {
    "BATCH_INIT":            {"history": True},
    "BATCH_FETCH_LIST":      {"history": True, "data_key": "fetch_list_result"},
    "BATCH_NOTIFY_TAXES":    {"history": True, "data_key": "batch_notify_ack", "need_user_said": True},
    "BATCH_DATA_INIT":       {"history": True, "data_key": "init_result"},
    "BATCH_CONFIRM_TAX":     {"history": True, "data_key": "batch_tax_confirm", "need_user_said": True},
    "BATCH_SUBMIT":          {"history": True, "data_key": "submit_result"},
    "BATCH_DOWNLOAD":        {"history": True},
    "BATCH_NOTIFY_COMPLETE": {"history": True, "data_key": "batch_complete_ack", "need_user_said": True},
}


def _reverse_verify(state: dict, target_state: str) -> dict | None:
    if target_state not in BATCH_STATE_CHAIN:
        return None
    target_idx = BATCH_STATE_CHAIN.index(target_state)
    history_states = [h["state"] for h in state.get("state_history", [])]

    for i in range(target_idx - 1, -1, -1):
        check_state = BATCH_STATE_CHAIN[i]
        evidence = BATCH_STATE_EVIDENCE.get(check_state, {})

        if evidence.get("history") and check_state not in history_states:
            return {
                "broken_at": check_state,
                "reason": f"状态 {check_state} 从未被执行过",
                "chain_position": i,
            }
        data_key = evidence.get("data_key")
        if data_key:
            data_value = state["data"].get(data_key)
            if data_value is None:
                return {
                    "broken_at": check_state,
                    "reason": f"状态 {check_state} 的产出数据 '{data_key}' 不存在",
                    "chain_position": i,
                }
            if evidence.get("need_user_said"):
                if isinstance(data_value, dict) and not data_value.get("user_said"):
                    return {
                        "broken_at": check_state,
                        "reason": f"状态 {check_state} 的 user_said 为空",
                        "chain_position": i,
                    }
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 用户友好提示
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _user_msg(task_id: str, status: str, text: str,
              waiting_for: str = None, summary: dict = None) -> dict:
    r = {"ok": status != "error", "task_id": task_id, "status": status, "user_message": text}
    if waiting_for:
        r["waiting_for"] = waiting_for
    if summary:
        r["summary"] = summary
    return r


def _format_blocked(state_name: str, state: dict) -> str:
    batch_name = state.get("batch_name", "批量申报")
    period = state["period"]
    tax_type_name = _tax_type_name(state.get("tax_type", "vat"))
    companies = state.get("companies", [])

    if state_name == "BATCH_NOTIFY_TAXES":
        fetch_result = state["data"].get("fetch_list_result", {})
        results = fetch_result.get("results", [])

        lines = [f"已查询到 {len(results)} 家企业 {period} 月{tax_type_name}申报清册：\n"]
        for i, r in enumerate(results, 1):
            name = r.get("company_name", "")
            req_count = r.get("required_count", 0)
            items = r.get("required_items", [])
            status_list = []
            for it in items:
                it_name = it.get("zsxmMc", "")
                it_status = it.get("declareStatus", "待申报")
                status_list.append(f"{it_name}({it_status})")
            lines.append(f"{i}. {name}: {', '.join(status_list) if status_list else f'{req_count}个税种待申报'}")

        lines.append(f"\n共 {len(companies)} 家企业全部就绪。是否开始批量申报？")
        return "\n".join(lines)

    elif state_name == "BATCH_CONFIRM_TAX":
        init_result = state["data"].get("init_result", {})
        results = init_result.get("results", [])

        lines = [f"{period} 月{tax_type_name}批量初始化数据汇总：\n"]
        for i, r in enumerate(results, 1):
            name = r.get("company_name", "")
            tax_results = r.get("results", [])
            status_parts = []
            for tr in tax_results:
                s = tr.get("status", "")
                tn = tr.get("tax_name", "")
                if s == "already_declared":
                    status_parts.append(f"{tn}(已申报)")
                elif s == "initialized":
                    status_parts.append(f"{tn}(已初始化)")
                else:
                    status_parts.append(f"{tn}({s})")
            lines.append(f"{i}. {name}: {', '.join(status_parts)}")

        lines.append(f"\n{len(results)} 家企业全部初始化成功。确认无误？确认后将批量提交申报。")
        return "\n".join(lines)

    elif state_name == "BATCH_NOTIFY_COMPLETE":
        submit_result = state["data"].get("submit_result", {})
        download_result = state["data"].get("download_result", {})
        s_results = submit_result.get("results", [])
        d_results = download_result.get("results", [])

        lines = [f"{batch_name}已完成！\n"]
        lines.append(f"✅ {len(s_results)} 家企业全部申报成功：")
        for sr in s_results:
            name = sr.get("company_name", "")
            tax_amt = sr.get("data", {}).get("taxAmount", "0")
            lines.append(f"  - {name}: 税额 ¥{tax_amt}")

        if d_results:
            lines.append(f"\n📄 PDF 已全部下载（{len(d_results)} 份）")

        lines.append("\n请确认收到以上信息。")
        return "\n".join(lines)

    return BATCH_STATE_DEFS.get(state_name, {}).get("message", "请回复以继续。")


def _format_summary(summary: dict) -> str:
    if not summary:
        return "批量申报流程已完成。"
    msg = summary.get("message", "")
    if msg:
        return msg
    return f"批量申报完成（{summary.get('status', 'unknown')}）。"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# advance / inject
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def advance(task_id: str) -> dict:
    state = _load_batch_state(task_id)
    if not state:
        return _user_msg(task_id, "error", "批量任务不存在，请重新创建。")

    MAX_AUTO_STEPS = 20

    for _loop in range(MAX_AUTO_STEPS):
        state = _load_batch_state(task_id)
        if not state:
            return _user_msg(task_id, "error", "批量任务不存在，请重新创建。")

        current = state["state"]
        defn = BATCH_STATE_DEFS.get(current)
        if not defn:
            return _user_msg(task_id, "error", "系统异常，请联系管理员。")

        if defn["type"] == "terminal":
            handler = BATCH_HANDLER_MAP[defn["handler"]]
            result = handler(state)
            summary = result.get("summary", {})
            return _user_msg(task_id, "completed", _format_summary(summary), summary=summary)

        if defn["type"] == "input":
            required_key = defn["required_input"]
            if required_key not in state["data"] or state["data"][required_key] is None:
                return _user_msg(task_id, "need_input",
                                 _format_blocked(current, state),
                                 waiting_for=required_key)

            input_data = state["data"][required_key]
            if isinstance(input_data, dict) and "user_said" not in input_data:
                return _user_msg(task_id, "error", "缺少用户确认信息，请重新回复。")

        chain_error = _reverse_verify(state, current)
        if chain_error:
            return _user_msg(task_id, "error",
                             f"流程异常：{chain_error['reason']}，请联系管理员。")

        handler = BATCH_HANDLER_MAP[defn["handler"]]
        log.info(f"[{task_id}] 执行: {current}")
        result = handler(state)

        if result.get("blocked"):
            return _user_msg(task_id, "error",
                             result.get("error", "操作失败，请稍后重试。"))

        if result.get("terminal"):
            summary = result.get("summary", {})
            return _user_msg(task_id, "completed", _format_summary(summary), summary=summary)

        next_state = result["next"]
        transition(state, next_state, f"from_{current}")

        next_defn = BATCH_STATE_DEFS.get(next_state, {})

        if next_defn.get("type") == "input":
            return _user_msg(task_id, "need_input",
                             _format_blocked(next_state, state),
                             waiting_for=next_defn.get("required_input"))

        if next_defn.get("type") == "terminal":
            continue

    return _user_msg(task_id, "error", "流程步骤过多，请联系管理员。")


def inject_data(task_id: str, data_key: str, data_value) -> dict:
    state = _load_batch_state(task_id)
    if not state:
        return {"ok": False, "error": f"批量任务不存在: {task_id}"}

    current = state["state"]
    defn = BATCH_STATE_DEFS.get(current, {})

    chain_error = _reverse_verify(state, current)
    if chain_error:
        return {
            "ok": False,
            "error": f"反向验证失败: {chain_error['reason']}",
            "task_id": task_id,
        }

    if defn.get("type") != "input":
        return {
            "ok": False,
            "error": f"当前状态 {current} 不接受输入（类型: {defn.get('type')}）",
            "task_id": task_id,
        }

    expected = defn.get("required_input")
    if data_key != expected:
        return {
            "ok": False,
            "error": f"当前状态 {current} 只接受 key='{expected}'，你传的是 '{data_key}'",
            "task_id": task_id,
        }

    if isinstance(data_value, dict) and "user_said" not in data_value:
        return {
            "ok": False,
            "error": "inject 数据必须包含 'user_said' 字段",
            "task_id": task_id,
        }

    state["data"][data_key] = data_value
    _save_batch_state(task_id, state)
    log.info(f"[{task_id}] ✅ inject {data_key} at state {current}")

    return {"ok": True, "message": f"已注入 {data_key}", "state": current, "task_id": task_id}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 持久化（复用 shared.py 的 STATE_DIR）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _batch_state_path(task_id: str) -> Path:
    return STATE_DIR / f"{task_id}.json"

def _save_batch_state(task_id: str, state: dict):
    state["updated_at"] = now_iso()
    with open(_batch_state_path(task_id), "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _load_batch_state(task_id: str) -> dict | None:
    p = _batch_state_path(task_id)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "status")

    if action == "create":
        state = create_batch_task(
            companies=args["companies"],
            period=args["period"],
            tax_type=args.get("tax_type", "vat"),
            batch_name=args.get("batch_name", ""),
        )
        result = advance(state["task_id"])
        output(result)

    elif action == "advance":
        result = advance(args["task_id"])
        output(result)

    elif action == "inject":
        result = inject_data(args["task_id"], args["data_key"], args["data_value"])
        output(result)

    elif action == "status":
        state = _load_batch_state(args.get("task_id", ""))
        if state:
            current = state["state"]
            defn = BATCH_STATE_DEFS.get(current, {})
            output({
                "ok": True,
                "task_id": state["task_id"],
                "state": current,
                "state_type": defn.get("type"),
                "waiting_for": defn.get("required_input") if defn.get("type") == "input" else None,
                "batch_name": state["batch_name"],
                "period": state["period"],
                "tax_type": state["tax_type"],
                "company_count": state["company_count"],
                "last_updated": state["updated_at"],
            })
        else:
            output({"ok": False, "error": "批量任务不存在"})

    elif action == "list":
        tasks = []
        for f in STATE_DIR.glob("batch_*.json"):
            with open(f) as fh:
                t = json.load(fh)
                tasks.append({
                    "task_id": t["task_id"],
                    "state": t["state"],
                    "batch_name": t.get("batch_name", ""),
                    "period": t["period"],
                    "tax_type": t.get("tax_type", ""),
                    "company_count": t.get("company_count", 0),
                })
        output({"ok": True, "tasks": tasks})

    else:
        output({"ok": False, "error": f"未知 action: {action}"})
