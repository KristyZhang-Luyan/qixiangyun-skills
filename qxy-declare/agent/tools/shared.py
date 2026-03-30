"""
共享工具库 — 企享云 MCP 适配版

替换说明：
  - api_call()  → 内部走 qxy_mcp_lib.call_tool()
  - poll_task() → 内部走 qxy_mcp_lib.poll_tool()
  - 去掉：签名逻辑、Token 管理、requests 依赖、config.json 依赖
  - 凭证来源：.env 文件或环境变量（QXY_CLIENT_APPKEY / QXY_CLIENT_SECRET）
  - 状态持久化、create_task、output、parse_args 等函数签名不变
"""

import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

# ── 日志 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    encoding="utf-8",
)
log = logging.getLogger("qxy")

# ── MCP 库导入 ────────────────────────────────────────
from qxy_mcp_lib import (
    QXYAuthError,
    QXYMCPError,
    call_tool as mcp_call_tool,
    poll_tool as mcp_poll_tool,
)

# ── 状态目录 ──────────────────────────────────────────
STATE_DIR = Path(os.environ.get("QXY_STATE_DIR", "/tmp/qxy-states"))
STATE_DIR.mkdir(parents=True, exist_ok=True)

# ── 轮询配置 ──────────────────────────────────────────
POLL_INTERVAL = int(os.environ.get("QXY_POLL_INTERVAL", "10"))
POLL_MAX = int(os.environ.get("QXY_POLL_MAX", "30"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REST endpoint_key → MCP (service, tool) 映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENDPOINT_TO_MCP = {
    # ── 企业画像 ──────────────────────────────────
    "initiate_enterprise_data_collection":  ("enterprise_profiling_service", "initiate_enterprise_data_collection_auto"),
    "get_collection_status_and_full_data":  ("enterprise_profiling_service", "get_collection_status_and_full_data_auto"),

    # ── 申报 ──────────────────────────────────────
    "initiate_roster_entry":         ("roster_entry", "initiate_declaration_entry_task_auto"),
    "query_roster_result":           ("roster_entry", "query_roster_entry_task_auto"),

    "load_init_data_task":           ("initialize_data", "load_init_data_task"),
    "get_init_data":                 ("initialize_data", "get_init_data"),

    "upload_tax_report":             ("declaration_submission", "upload_tax_report_data_auto"),
    "query_tax_report_result":       ("declaration_submission", "query_upload_tax_report_result_auto"),

    "upload_financial_report":       ("declaration_submission", "upload_financial_report_data"),
    "upload_financial_report_excel": ("declaration_submission", "upload_tax_report_data_excel_auto"),
    "query_financial_report_result": ("declaration_submission", "query_upload_financial_report_result_auto"),

    "simplified_declare":            ("declaration_submission", "upload_tax_report_data_auto"),
    "query_simplified_result":       ("declaration_submission", "query_upload_tax_report_result_auto"),

    "load_pdf_task":                 ("pdf_download", "load_pdf_task"),
    "load_wq_pdf_task":              ("pdf_download", "load_wq_pdf_task"),
    "query_pdf_result":              ("pdf_download", "query_pdf_task_result_auto"),

    "load_declare_info_task":        ("declaration_query", "load_declare_info_task"),

    "initiate_missing_check":        ("missing_declaration_check", "initiate_missing_declaration_check_task_auto"),

    # ── 缴款 ──────────────────────────────────────
    "load_payment_task":             ("tax_payment", "load_payment_task"),
    "query_payment_result":          ("tax_payment", "query_tax_payment_task_result_auto"),

    "load_wszm_task":                ("tax_payment_certificate", "initiate_wszm_parse_task_auto"),
    "query_wszm_result":             ("tax_payment_certificate", "query_wszm_parse_task_result_auto"),
}

# 登录类端点无 MCP 映射
_LOGIN_ENDPOINTS = {
    "auth", "check_quick_login", "login_tax_bureau",
    "create_company", "create_account",
    "query_org_info", "get_org_info_result",
}

# service → 默认轮询 query tool
SERVICE_POLL_TOOL = {
    "enterprise_profiling_service": "get_collection_status_and_full_data_auto",
    "roster_entry":              "query_roster_entry_task_auto",
    "initialize_data":           "get_init_data",
    "declaration_submission":    "query_upload_tax_report_result_auto",
    "pdf_download":              "query_pdf_task_result_auto",
    "declaration_query":         "query_declare_info_task_result_auto",
    "missing_declaration_check": "query_missing_declaration_check_task_auto",
    "tax_payment":               "query_tax_payment_task_result_auto",
    "tax_payment_certificate":   "query_wszm_parse_task_result_auto",
}

# 上一次 api_call 的 service（供 poll_task 自动路由）
_last_call_context = {"service": ""}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# api_call — 签名兼容旧版，内部走 MCP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def api_call(endpoint_key: str, method: str = "POST", payload: dict = None,
             raw_url: str = None) -> dict:
    """
    调用企享云接口（通过 MCP 协议）。
    返回格式不变：{"ok": True/False, "data": ..., "code": ..., "message": ...}
    """
    if raw_url:
        log.warning("raw_url 在 MCP 模式下不支持，忽略: %s", raw_url)

    # 登录类端点无 MCP 映射
    if endpoint_key in _LOGIN_ENDPOINTS:
        return {
            "ok": False,
            "error": f"端点 '{endpoint_key}' 无 MCP 映射，请使用 login-api-skill",
            "code": "NO_MCP_MAPPING",
        }

    # query_task_info 不再直接调用
    if endpoint_key == "query_task_info":
        return {
            "ok": False,
            "error": "query_task_info 已由 poll_task() 内部处理",
            "code": "USE_POLL_TASK",
        }

    mapping = ENDPOINT_TO_MCP.get(endpoint_key)
    if mapping is None:
        return {"ok": False, "error": f"未知端点: {endpoint_key}", "code": "UNKNOWN"}

    service, tool = mapping

    try:
        result = mcp_call_tool(service, tool, payload or {})
        _last_call_context["service"] = service

        # 标准化为旧版返回格式
        if not isinstance(result, dict):
            return {"ok": True, "data": result, "code": "", "message": ""}

        code = str(result.get("code", ""))
        success = result.get("success", False)
        msg = result.get("message", result.get("msg", ""))

        if code in ("2000", "SUCCESS", "") or success:
            return {"ok": True, "data": result, "code": code, "message": msg}
        else:
            return {
                "ok": False, "data": result, "code": code,
                "message": msg,
                "error": msg or f"业务错误: code={code}",
            }

    except QXYAuthError as e:
        log.error("MCP 认证失败: %s", e)
        return {"ok": False, "error": str(e), "code": "AUTH_ERROR", "message": str(e)}
    except QXYMCPError as e:
        log.error("MCP 调用失败 [%s/%s]: %s", service, tool, e)
        return {"ok": False, "error": str(e), "code": "MCP_ERROR", "message": str(e)}
    except Exception as e:
        log.error("api_call 异常 [%s]: %s", endpoint_key, e)
        return {"ok": False, "error": str(e)}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# poll_task — 签名兼容旧版，内部走 MCP poll_tool
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def poll_task(agg_org_id, task_id,
              interval: int = None, max_attempts: int = None,
              result_endpoint: str = None) -> dict:
    """
    轮询异步任务（通过 MCP 协议）。
    返回格式不变：{"ok": True/False, "status": "completed/failed/processing", "data": ..., "poll_attempts": ...}
    """
    interval = interval or POLL_INTERVAL
    max_attempts = max_attempts or POLL_MAX

    # 1. 确定 service 和 tool
    poll_service = None
    poll_tool_name = None

    if result_endpoint:
        mapping = ENDPOINT_TO_MCP.get(result_endpoint)
        if mapping:
            poll_service, poll_tool_name = mapping

    if not poll_service:
        poll_service = _last_call_context.get("service", "")

    if not poll_service:
        return {
            "ok": False, "status": "error",
            "error": "无法确定轮询 service（请确保先调用了 api_call）",
            "poll_attempts": 0,
        }

    if not poll_tool_name:
        poll_tool_name = SERVICE_POLL_TOOL.get(poll_service)

    if not poll_tool_name:
        return {
            "ok": False, "status": "error",
            "error": f"service '{poll_service}' 无已知轮询 tool",
            "poll_attempts": 0,
        }

    # 2. 执行轮询
    try:
        poll_result = mcp_poll_tool(
            service_name=poll_service,
            tool_name=poll_tool_name,
            tool_args={"aggOrgId": str(agg_org_id), "taskId": str(task_id)},
            interval_seconds=interval,
            max_attempts=max_attempts,
        )
    except QXYMCPError as e:
        log.error("MCP 轮询失败 [%s/%s]: %s", poll_service, poll_tool_name, e)
        return {"ok": False, "status": "error", "error": str(e), "poll_attempts": 0}

    # 3. 标准化返回
    state = poll_result.get("state", "unknown")
    attempts = poll_result.get("attempts", 0)
    data = poll_result.get("result", {})

    if state == "success":
        return {"ok": True, "status": "completed", "data": data, "poll_attempts": attempts}
    elif state == "failed":
        error_msg = ""
        if isinstance(data, dict):
            error_msg = data.get("message", data.get("msg", "任务失败"))
        return {"ok": False, "status": "failed", "data": data,
                "error": error_msg or "任务失败", "poll_attempts": attempts}
    elif state == "timeout":
        return {"ok": False, "status": "processing",
                "error": f"轮询 {attempts} 次后仍在处理中", "poll_attempts": attempts}
    else:
        return {"ok": False, "status": state, "data": data,
                "error": f"未知状态: {state}", "poll_attempts": attempts}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 以下完全不变：状态持久化 + 工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _state_path(task_id: str) -> Path:
    return STATE_DIR / f"{task_id}.json"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def create_task(company_id: str, company_name: str, period: str,
                agg_org_id: str = "", company_type: str = "small_scale") -> dict:
    task_id = f"decl_{period.replace('-', '')}_{company_id}"
    state = {
        "task_id": task_id,
        "company_id": company_id,
        "company_name": company_name,
        "agg_org_id": agg_org_id,
        "company_type": company_type,
        "period": period,
        "state": "INIT",
        "state_history": [],
        "data": {
            "enterprise_profile": None,
            "tax_list": None,
            "declaration_forms": None,
            "init_data": None,
            "parsed_excel": None,
            "user_confirmations": None,
            "calculated_taxes": None,
            "policy_matches": None,
            "validation_result": None,
            "submit_result": None,
            "declare_video": None,
            "receipt_url": None,
            "receipt_data": None,
        },
        "interactions": {},
        "retry_count": 0,
        "max_retries": 3,
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save_state(task_id, state)
    return state

def load_state(task_id: str) -> dict | None:
    p = _state_path(task_id)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f)

def save_state(task_id: str, state: dict):
    state["updated_at"] = now_iso()
    with open(_state_path(task_id), "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def transition(state: dict, new_state: str, result: str = "ok") -> dict:
    state["state_history"].append({
        "state": state["state"],
        "at": now_iso(),
        "result": result,
    })
    state["state"] = new_state
    state["retry_count"] = 0
    state["error"] = None
    save_state(state["task_id"], state)
    log.info(f"[{state['task_id']}] {state['state_history'][-1]['state']} → {new_state} ({result})")
    return state

def fail(state: dict, error: str) -> dict:
    state["error"] = error
    state["retry_count"] += 1
    save_state(state["task_id"], state)
    log.error(f"[{state['task_id']}] FAILED at {state['state']}: {error} (retry {state['retry_count']})")
    return state

def list_tasks(status_filter: str = None) -> list:
    tasks = []
    for f in STATE_DIR.glob("*.json"):
        with open(f) as fh:
            task = json.load(fh)
            if status_filter is None or task["state"] == status_filter:
                tasks.append(task)
    return tasks

def output(result: dict):
    print(json.dumps(result, ensure_ascii=False, indent=2))

def parse_args() -> dict:
    if len(sys.argv) > 1:
        return json.loads(sys.argv[1])
    if not sys.stdin.isatty():
        import select
        if select.select([sys.stdin], [], [], 0.1)[0]:
            raw = sys.stdin.read().strip()
            if raw:
                return json.loads(raw)
    return {}
