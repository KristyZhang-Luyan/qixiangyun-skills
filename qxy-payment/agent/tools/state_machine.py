#!/usr/bin/env python3
"""
state_machine.py — 缴费流程状态机

流程（对照流程图，默认三方协议直接扣款，跳过 <1 元判断）：
  INIT → CONFIRM_PAYMENT → EXECUTE_PAY → CHECK_RESULT → DOWNLOAD_CERT → NOTIFY_COMPLETE → DONE

规则与 qxy-declare 一致：
  1. advance() 每次只执行一步
  2. input 类型状态必须等外部 inject 数据
  3. blocked 就是停，等用户交互
  4. inject 必须带 user_said
"""

import json
from shared import (
    create_task, load_state, save_state, transition, fail,
    list_tasks, output, parse_args, log, now_iso,
)
from payment import execute_payment, download_tax_certificate


def _parse_period(p: str) -> tuple[int, int]:
    parts = p.split("-")
    return int(parts[0]), int(parts[1])


STATE_DEFS = {
    "INIT": {
        "type": "auto",
        "handler": "do_init",
    },
    "CONFIRM_PAYMENT": {
        "type": "input",
        "required_input": "payment_confirm",
        "handler": "do_confirm_payment",
        "message": (
            "【必须和用户交互】请向用户展示应缴税款明细（税种、金额），确认是否缴款。\n"
            "缴款方式为三方协议直接银行扣款。\n"
            "用户确认后 inject:\n"
            'data_key="payment_confirm" data_value={"user_said": "用户的原话"}'
        ),
    },
    "EXECUTE_PAY": {
        "type": "auto",
        "handler": "do_execute_pay",
    },
    "CHECK_RESULT": {
        "type": "auto",
        "handler": "do_check_result",
    },
    "DOWNLOAD_CERT": {
        "type": "auto",
        "handler": "do_download_cert",
    },
    "NOTIFY_COMPLETE": {
        "type": "input",
        "required_input": "complete_ack",
        "handler": "do_notify_complete",
        "message": (
            "【必须和用户交互】请向用户发送缴费结果通知（成功/失败、税额、完税证明），\n"
            "用户确认收到后 inject:\n"
            'data_key="complete_ack" data_value={"user_said": "用户的原话"}'
        ),
    },
    "DONE": {
        "type": "terminal",
        "handler": "do_done",
    },
    "FAILED": {
        "type": "terminal",
        "handler": "do_failed",
    },
}


STATE_CHAIN = [
    "INIT",
    "CONFIRM_PAYMENT",
    "EXECUTE_PAY",
    "CHECK_RESULT",
    "DOWNLOAD_CERT",
    "NOTIFY_COMPLETE",
    "DONE",
]

STATE_EVIDENCE = {
    "INIT":             {"history": True},
    "CONFIRM_PAYMENT":  {"history": True, "data_key": "payment_confirm", "need_user_said": True},
    "EXECUTE_PAY":      {"history": True, "data_key": "pay_result"},
    "CHECK_RESULT":     {"history": True},
    "DOWNLOAD_CERT":    {"history": True},
    "NOTIFY_COMPLETE":  {"history": True, "data_key": "complete_ack", "need_user_said": True},
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 状态处理函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def do_init(state: dict) -> dict:
    """从申报结果中提取缴费所需信息"""
    agg = state["agg_org_id"]
    if not agg:
        return {"blocked": True, "error": "缺少 agg_org_id"}

    declare_result = state["data"].get("declare_result", {})
    total_payable = declare_result.get("total_payable", 0)
    tax_details = declare_result.get("tax_details", [])

    state["data"]["payable_amount"] = total_payable
    state["data"]["tax_details"] = tax_details
    save_state(state["task_id"], state)

    log.info(f"[{state['task_id']}] INIT: 应缴税款 ¥{total_payable}")
    return {"next": "CONFIRM_PAYMENT"}


def do_confirm_payment(state: dict) -> dict:
    """用户已确认缴款 → 进入执行"""
    return {"next": "EXECUTE_PAY"}


def do_execute_pay(state: dict) -> dict:
    """调用缴款接口（三方协议直接银行扣款）"""
    year, period = _parse_period(state["period"])
    agg = state["agg_org_id"]
    payment_detail = state["data"].get("payment_detail", [])

    result = execute_payment(agg, year, period, payment_detail)
    state["data"]["pay_result"] = result
    save_state(state["task_id"], state)

    if not result["ok"]:
        if result.get("retryable"):
            fail(state, result.get("error"))
            if state["retry_count"] < state["max_retries"]:
                return {"blocked": True, "error": f"缴款失败(可重试): {result.get('error')}"}
            return {"next": "FAILED"}
        fail(state, result.get("error"))
        return {"next": "FAILED"}

    return {"next": "CHECK_RESULT"}


def do_check_result(state: dict) -> dict:
    """检查缴款结果"""
    pay_result = state["data"].get("pay_result", {})

    if pay_result.get("ok") and pay_result.get("status") == "success":
        log.info(f"[{state['task_id']}] 缴款成功")
        return {"next": "DOWNLOAD_CERT"}

    error = pay_result.get("error", "缴款结果未知")
    fail(state, error)
    if state["retry_count"] < state["max_retries"]:
        return {"blocked": True, "error": f"缴款结果异常: {error}"}
    return {"next": "FAILED"}


def do_download_cert(state: dict) -> dict:
    """下载完税证明"""
    year, period = _parse_period(state["period"])
    agg = state["agg_org_id"]
    zsxm_list = state["data"].get("zsxm_list", [])

    result = download_tax_certificate(agg, year, period, zsxm_list)
    state["data"]["certificate"] = result
    save_state(state["task_id"], state)

    if not result["ok"]:
        log.warning(f"[{state['task_id']}] 完税证明下载失败: {result.get('error')}，继续流程")

    return {"next": "NOTIFY_COMPLETE"}


def do_notify_complete(state: dict) -> dict:
    """用户确认收到通知 → 完成"""
    return {"next": "DONE"}


def do_done(state: dict) -> dict:
    pay_result = state["data"].get("pay_result", {})
    cert = state["data"].get("certificate", {})
    return {
        "terminal": True,
        "summary": {
            "task_id": state["task_id"],
            "company_name": state["company_name"],
            "period": state["period"],
            "status": "completed",
            "payable_amount": state["data"].get("payable_amount", 0),
            "pay_status": pay_result.get("status", "unknown"),
            "has_certificate": cert.get("ok", False),
            "message": f"{state['company_name']} {state['period']} 缴费完成",
        },
    }


def do_failed(state: dict) -> dict:
    return {
        "terminal": True,
        "summary": {
            "task_id": state["task_id"],
            "company_name": state["company_name"],
            "period": state["period"],
            "status": "failed",
            "error": state.get("error"),
        },
    }


HANDLER_MAP = {
    "do_init": do_init,
    "do_confirm_payment": do_confirm_payment,
    "do_execute_pay": do_execute_pay,
    "do_check_result": do_check_result,
    "do_download_cert": do_download_cert,
    "do_notify_complete": do_notify_complete,
    "do_done": do_done,
    "do_failed": do_failed,
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 反向链路验证
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _reverse_verify(state: dict, target_state: str) -> dict | None:
    if target_state not in STATE_CHAIN:
        return None

    target_idx = STATE_CHAIN.index(target_state)
    history_states = [h["state"] for h in state.get("state_history", [])]

    for i in range(target_idx - 1, -1, -1):
        check_state = STATE_CHAIN[i]
        evidence = STATE_EVIDENCE.get(check_state, {})

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
# advance / inject
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _user_msg(task_id: str, status: str, text: str,
              waiting_for: str = None, summary: dict = None) -> dict:
    """统一输出：纯文本 user_message + 最少结构化字段"""
    r = {"ok": status != "error", "task_id": task_id, "status": status, "user_message": text}
    if waiting_for:
        r["waiting_for"] = waiting_for
    if summary:
        r["summary"] = summary
    return r


def _format_blocked(state_name: str, state: dict) -> str:
    """根据 blocked 状态生成用户友好中文提示"""
    company = state["company_name"]
    period = state["period"]
    amount = state["data"].get("payable_amount", 0)
    details = state["data"].get("tax_details", [])
    pay_result = state["data"].get("pay_result", {})
    cert = state["data"].get("certificate", {})

    if state_name == "CONFIRM_PAYMENT":
        lines = [f"{company} {period} 月应缴税款明细：\n"]
        for d in details:
            name = d.get("tax_name", d.get("zsxmMc", "税种"))
            amt = d.get("final_amount", d.get("amount", 0))
            lines.append(f"- {name}: ¥{amt:,.2f}")
        lines.append(f"\n应缴总额: ¥{amount:,.2f}")
        lines.append("\n缴款方式: 三方协议直接银行扣款")
        lines.append("请确认是否缴款？")
        return "\n".join(lines)

    elif state_name == "NOTIFY_COMPLETE":
        pay_ok = pay_result.get("ok", False)
        pay_data = pay_result.get("data", {})
        pay_amount = f"{amount:,.2f}" if amount else pay_data.get("paymentAmount", "0.00")
        pay_time = pay_data.get("paymentTime", "")

        cert_ok = cert.get("ok", False)
        cert_no = ""
        if cert_ok:
            cd = cert.get("data", {})
            if isinstance(cd, dict):
                inner = cd.get("data", cd)
                if isinstance(inner, dict):
                    wszm = inner.get("wszmData", {})
                    cert_no = wszm.get("certificate_no", "")

        if pay_ok:
            text = f"缴款成功！\n缴款金额: ¥{pay_amount}\n缴款方式: 三方协议银行扣款"
            if pay_time:
                text += f"\n缴款时间: {pay_time}"
            if cert_ok and cert_no:
                text += f"\n完税证明编号: {cert_no}"
            elif cert_ok:
                text += "\n完税证明已获取。"
            text += "\n请确认收到以上信息。"
            return text
        else:
            return f"缴款处理完成，请确认收到。"

    return STATE_DEFS.get(state_name, {}).get("message", "请回复以继续。")


def _format_summary(summary: dict) -> str:
    if not summary:
        return "缴费流程已完成。"
    msg = summary.get("message", "")
    if msg:
        return msg
    company = summary.get("company_name", "")
    period = summary.get("period", "")
    return f"{company} {period} 月缴费完成。"


def advance(task_id: str) -> dict:
    state = load_state(task_id)
    if not state:
        return _user_msg(task_id, "error", "任务不存在，请重新创建。")

    MAX_AUTO_STEPS = 20

    for _loop in range(MAX_AUTO_STEPS):
        state = load_state(task_id)
        if not state:
            return _user_msg(task_id, "error", "任务不存在，请重新创建。")

        current = state["state"]
        defn = STATE_DEFS.get(current)
        if not defn:
            return _user_msg(task_id, "error", "系统异常，请联系管理员。")

        if defn["type"] == "terminal":
            handler = HANDLER_MAP[defn["handler"]]
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

        handler = HANDLER_MAP[defn["handler"]]
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

        next_defn = STATE_DEFS.get(next_state, {})

        if next_defn.get("type") == "input":
            return _user_msg(task_id, "need_input",
                             _format_blocked(next_state, state),
                             waiting_for=next_defn.get("required_input"))

        if next_defn.get("type") == "terminal":
            continue

    return _user_msg(task_id, "error", "流程步骤过多，请联系管理员。")


def inject_data(task_id: str, data_key: str, data_value) -> dict:
    state = load_state(task_id)
    if not state:
        return {"ok": False, "error": f"任务不存在: {task_id}"}

    current = state["state"]
    defn = STATE_DEFS.get(current, {})

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
    save_state(task_id, state)
    log.info(f"[{task_id}] inject {data_key} at state {current}")

    return {"ok": True, "message": f"已注入 {data_key}", "state": current, "task_id": task_id}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "status")

    if action == "create":
        state = create_task(
            company_id=args["company_id"],
            company_name=args["company_name"],
            period=args["period"],
            agg_org_id=str(args.get("agg_org_id", "")),
            company_type=args.get("company_type", "small_scale"),
        )
        if args.get("declare_result"):
            state["data"]["declare_result"] = args["declare_result"]
            save_state(state["task_id"], state)
        result = advance(state["task_id"])
        output(result)

    elif action == "advance":
        result = advance(args["task_id"])
        output(result)

    elif action == "inject":
        result = inject_data(args["task_id"], args["data_key"], args["data_value"])
        output(result)

    elif action == "status":
        state = load_state(args.get("task_id", ""))
        if state:
            current = state["state"]
            defn = STATE_DEFS.get(current, {})
            output({
                "ok": True,
                "task_id": state["task_id"],
                "state": current,
                "state_type": defn.get("type"),
                "waiting_for": defn.get("required_input") if defn.get("type") == "input" else None,
                "company_name": state["company_name"],
                "period": state["period"],
            })
        else:
            output({"ok": False, "error": "任务不存在"})

    elif action == "list":
        tasks = list_tasks(args.get("status_filter"))
        output({
            "ok": True,
            "tasks": [{
                "task_id": t["task_id"],
                "state": t["state"],
                "company_name": t["company_name"],
                "period": t["period"],
            } for t in tasks],
        })

    else:
        output({"ok": False, "error": f"未知 action: {action}"})