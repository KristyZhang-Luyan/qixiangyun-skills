#!/usr/bin/env python3
"""
check_submit_result — 查询申报提交结果（支持轮询）
输入: {"submission_id": "xxx", "poll": false, "poll_interval": 5, "poll_max": 12}
输出: {"ok": true, "status": "success/processing/rejected", ...}
"""

import time
from shared import api_call, output, parse_args, log


def check_once(submission_id: str) -> dict:
    result = api_call("check_result", payload={
        "submission_id": submission_id,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result["error"],
            "status": "error",
        }

    data = result["data"]
    status = data.get("status", "unknown")

    resp = {
        "ok": True,
        "submission_id": submission_id,
        "status": status,
        "results": data.get("results", data.get("result", [])),
    }

    if status == "rejected":
        resp["rejection_reasons"] = data.get(
            "rejection_reasons",
            data.get("reasons", data.get("errors", []))
        )
        resp["message"] = "申报被拒绝"
    elif status == "success":
        resp["message"] = "申报成功"
    elif status == "processing":
        resp["message"] = "处理中，请稍后查询"

    return resp


def check_submit_result(submission_id: str, poll: bool = False,
                        poll_interval: int = 5, poll_max: int = 12) -> dict:
    if not poll:
        return check_once(submission_id)

    # 轮询模式
    for i in range(1, poll_max + 1):
        result = check_once(submission_id)
        status = result.get("status", "error")

        if status != "processing":
            result["poll_attempts"] = i
            return result

        log.info(f"[{submission_id}] 轮询第 {i}/{poll_max} 次，状态: processing")
        if i < poll_max:
            time.sleep(poll_interval)

    return {
        "ok": True,
        "submission_id": submission_id,
        "status": "processing",
        "message": f"轮询 {poll_max} 次后仍在处理中",
        "poll_attempts": poll_max,
    }


if __name__ == "__main__":
    args = parse_args()
    result = check_submit_result(
        submission_id=args.get("submission_id", ""),
        poll=args.get("poll", False),
        poll_interval=args.get("poll_interval", 5),
        poll_max=args.get("poll_max", 12),
    )
    output(result)
