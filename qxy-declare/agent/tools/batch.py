#!/usr/bin/env python3
"""
batch.py — 批量编排层

不修改 state_machine.py，仅在外层循环调用其现有函数。
支持：batch_create / batch_advance / batch_inject / batch_status

返回格式：
  {
    "ok": true,
    "results": [ ... 每个任务的原始返回 ... ],
    "user_message": "合并后的用户可读文本"
  }
"""

import json
import sys
from shared import parse_args, output, log, list_tasks, load_state
from state_machine import advance, inject_data, create_task


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# batch_create — 批量创建任务并推进到第一个交互节点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_create(companies: list) -> dict:
    """
    入参: [{"company_id": "...", "company_name": "...", "agg_org_id": "...", "period": "2026-03", ...}, ...]
    对每个企业调用 create_task + advance，收集结果。
    """
    results = []
    errors = []

    for comp in companies:
        try:
            state = create_task(
                company_id=comp["company_id"],
                company_name=comp["company_name"],
                period=comp["period"],
                agg_org_id=str(comp.get("agg_org_id", "")),
                company_type=comp.get("company_type", "small_scale"),
            )
            result = advance(state["task_id"])
            results.append(result)
        except Exception as e:
            log.error(f"batch_create 失败: {comp.get('company_id')}: {e}")
            errors.append({
                "company_id": comp.get("company_id"),
                "error": str(e),
            })

    return _build_response(results, errors, "创建")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# batch_advance — 批量推进
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_advance(task_ids: list) -> dict:
    """对每个 task_id 调用 advance，收集结果。"""
    results = []
    errors = []

    for tid in task_ids:
        try:
            result = advance(tid)
            results.append(result)
        except Exception as e:
            log.error(f"batch_advance 失败: {tid}: {e}")
            errors.append({"task_id": tid, "error": str(e)})

    return _build_response(results, errors, "推进")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# batch_inject — 批量注入同一个 data_key + data_value
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_inject(task_ids: list, data_key: str, data_value: dict) -> dict:
    """对每个 task_id 执行 inject + advance。"""
    results = []
    errors = []

    for tid in task_ids:
        try:
            inj = inject_data(tid, data_key, data_value)
            if not inj.get("ok"):
                errors.append({"task_id": tid, "error": inj.get("error")})
                continue
            result = advance(tid)
            results.append(result)
        except Exception as e:
            log.error(f"batch_inject 失败: {tid}: {e}")
            errors.append({"task_id": tid, "error": str(e)})

    return _build_response(results, errors, "注入")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# batch_status — 批量查询状态
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def batch_status(task_ids: list) -> dict:
    """查询多个任务的当前状态，返回汇总。"""
    items = []
    for tid in task_ids:
        state = load_state(tid)
        if state:
            items.append({
                "task_id": tid,
                "state": state["state"],
                "company_name": state["company_name"],
                "period": state["period"],
            })
        else:
            items.append({"task_id": tid, "state": "NOT_FOUND"})

    lines = ["任务状态汇总：\n"]
    for i, item in enumerate(items, 1):
        name = item.get("company_name", item["task_id"])
        lines.append(f"{i}. {name} — {item['state']}")

    return {
        "ok": True,
        "results": items,
        "user_message": "\n".join(lines),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 内部：合并多个任务结果为一条 user_message
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_response(results: list, errors: list, action_label: str) -> dict:
    """
    把多个单任务返回合并成一个批量响应。
    - 如果所有任务的 waiting_for 相同（都在同一个交互节点），合并展示
    - 否则逐条列出
    """
    all_ok = all(r.get("ok") for r in results) and not errors
    total = len(results) + len(errors)
    success_count = sum(1 for r in results if r.get("ok"))

    # 判断是否所有任务都停在同一个交互节点
    waiting_fors = set(r.get("waiting_for", "") for r in results if r.get("waiting_for"))
    all_same_wait = len(waiting_fors) == 1 and len(results) > 0

    lines = []

    if all_same_wait:
        # 合并展示模式：所有任务停在同一个节点
        wait_key = waiting_fors.pop()
        lines.append(f"已批量{action_label} {success_count}/{total} 个任务。\n")

        # 按任务逐个摘要
        for i, r in enumerate(results, 1):
            tid = r.get("task_id", "")
            state = load_state(tid)
            company = state["company_name"] if state else tid
            # 提取关键数据用于汇总
            msg = r.get("user_message", "")
            lines.append(f"━━━ {i}. {company} ━━━")
            lines.append(msg)
            lines.append("")

        if wait_key:
            lines.append(f"以上 {success_count} 个企业均等待您确认，统一回复即可。")
    else:
        # 逐条展示模式
        lines.append(f"批量{action_label}结果：成功 {success_count}/{total}\n")
        for i, r in enumerate(results, 1):
            tid = r.get("task_id", "")
            status = r.get("status", "")
            msg = r.get("user_message", "")
            state = load_state(tid)
            company = state["company_name"] if state else tid
            lines.append(f"{i}. {company}（{status}）")
            if msg:
                lines.append(f"   {msg}")

    # 错误信息
    if errors:
        lines.append(f"\n⚠️ {len(errors)} 个任务失败：")
        for e in errors:
            lines.append(f"  - {e.get('task_id', e.get('company_id', '?'))}: {e.get('error', '未知错误')}")

    # 汇总 waiting_for（批量 inject 时 Agent 需要知道）
    combined_waiting = list(waiting_fors)[0] if all_same_wait else None
    combined_task_ids = [r["task_id"] for r in results if r.get("task_id")]

    resp = {
        "ok": all_ok,
        "results": results,
        "task_ids": combined_task_ids,
        "user_message": "\n".join(lines),
    }
    if combined_waiting:
        resp["waiting_for"] = combined_waiting
    if errors:
        resp["errors"] = errors

    return resp


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "")

    if action == "batch_create":
        result = batch_create(args["companies"])
        output(result)

    elif action == "batch_advance":
        result = batch_advance(args["task_ids"])
        output(result)

    elif action == "batch_inject":
        result = batch_inject(
            task_ids=args["task_ids"],
            data_key=args["data_key"],
            data_value=args["data_value"],
        )
        output(result)

    elif action == "batch_status":
        result = batch_status(args["task_ids"])
        output(result)

    else:
        output({"ok": False, "error": f"未知 batch action: {action}，支持: batch_create / batch_advance / batch_inject / batch_status"})
