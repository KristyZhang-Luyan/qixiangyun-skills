#!/usr/bin/env python3
"""
login — 登录相关工具
对应企享云接口:
  - check_quick_login (api-164618489): 校验是否可快速登录
  - login_tax_bureau (api-164576229): 登录税局
"""

from shared import api_call, output, parse_args, log


def check_login_status(agg_org_id: str) -> dict:
    """检查当前企业是否可快速登录税局"""
    result = api_call("check_quick_login", payload={
        "aggOrgId": agg_org_id,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "can_quick_login": False,
            "error": result.get("error"),
            "need_relogin": True,
        }

    data = result["data"]
    can_login = data.get("data", data).get("canQuickLogin",
                data.get("data", data).get("result", False))

    return {
        "ok": True,
        "can_quick_login": bool(can_login),
        "need_relogin": not bool(can_login),
    }


def login_tax_bureau(agg_org_id: str) -> dict:
    """登录税局"""
    result = api_call("login_tax_bureau", payload={
        "aggOrgId": agg_org_id,
    })

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message")),
            "code": result.get("code"),
        }

    return {
        "ok": True,
        "message": "税局登录成功",
        "data": result.get("data"),
    }


def ensure_logged_in(agg_org_id: str) -> dict:
    """确保已登录（检查 + 自动登录）"""
    check = check_login_status(agg_org_id)

    if check.get("can_quick_login"):
        login_result = login_tax_bureau(agg_org_id)
        return login_result

    if check.get("need_relogin"):
        return {
            "ok": False,
            "error": "需要重新登录自然人",
            "need_natural_person_login": True,
        }

    return {"ok": True, "message": "登录状态有效"}


if __name__ == "__main__":
    args = parse_args()
    action = args.get("action", "ensure")
    agg_org_id = str(args.get("agg_org_id", args.get("aggOrgId", "")))

    if action == "check":
        result = check_login_status(agg_org_id)
    elif action == "login":
        result = login_tax_bureau(agg_org_id)
    else:
        result = ensure_logged_in(agg_org_id)
    output(result)
