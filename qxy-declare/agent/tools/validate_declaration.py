#!/usr/bin/env python3
"""
validate_declaration — 申报表校验（本地规则 + 远程预校验）

脚本节点：执行确定性规则校验。
如校验失败，输出错误详情供 Agent 分析决策。

输入: {"company_id": "xxx", "period": "2026-02", "forms": [...]}
输出: {"ok": true, "is_valid": true/false, "errors": [...], "warnings": [...]}
"""

from decimal import Decimal
from shared import api_call, output, parse_args, log


def d(v) -> Decimal:
    return Decimal(str(v or 0))


# ── 本地校验规则 ──────────────────────────────────────

def validate_required_fields(form: dict) -> list:
    """必填项校验"""
    errors = []
    required = form.get("required_fields", [])
    data = form.get("data", {})

    for field in required:
        if field not in data or data[field] is None or data[field] == "":
            errors.append({
                "field": field,
                "rule": "required",
                "message": f"必填项 [{field}] 未填写",
                "severity": "error",
                "source": "local",
            })
    return errors


def validate_numeric_range(form: dict) -> list:
    """数值范围校验"""
    errors = []
    data = form.get("data", {})
    rules = form.get("range_rules", {})

    for field, rule in rules.items():
        if field not in data:
            continue
        value = d(data[field])
        if "min" in rule and value < d(rule["min"]):
            errors.append({
                "field": field,
                "rule": "range_min",
                "message": f"[{field}] 值 {value} 小于最小值 {rule['min']}",
                "severity": "error",
                "source": "local",
            })
        if "max" in rule and value > d(rule["max"]):
            errors.append({
                "field": field,
                "rule": "range_max",
                "message": f"[{field}] 值 {value} 大于最大值 {rule['max']}",
                "severity": "warning",
                "source": "local",
            })
    return errors


def validate_cross_check(form: dict) -> list:
    """勾稽关系校验"""
    errors = []
    data = form.get("data", {})
    checks = form.get("cross_checks", [])

    for check in checks:
        # 格式: {"left": "field_a + field_b", "right": "field_c", "tolerance": 0.01}
        try:
            left_val = eval(check["left"], {"__builtins__": {}}, data)
            right_val = eval(check["right"], {"__builtins__": {}}, data)
            tolerance = d(check.get("tolerance", 0.01))

            if abs(d(left_val) - d(right_val)) > tolerance:
                errors.append({
                    "field": f"{check['left']} vs {check['right']}",
                    "rule": "cross_check",
                    "message": f"勾稽关系不平: {check['left']}={left_val}, {check['right']}={right_val}",
                    "severity": "error",
                    "source": "local",
                })
        except Exception as e:
            log.warning(f"勾稽校验表达式执行失败: {e}")
            continue

    return errors


def validate_negative_check(form: dict) -> list:
    """负数校验"""
    errors = []
    data = form.get("data", {})
    non_negative = form.get("non_negative_fields", [])

    for field in non_negative:
        if field in data and d(data[field]) < 0:
            errors.append({
                "field": field,
                "rule": "non_negative",
                "message": f"[{field}] 不允许为负数，当前值: {data[field]}",
                "severity": "error",
                "source": "local",
            })
    return errors


# ── 本地校验主函数 ────────────────────────────────────

def local_validate(forms: list) -> tuple[list, list]:
    """执行所有本地校验，返回 (errors, warnings)"""
    errors = []
    warnings = []

    for form in forms:
        for check_fn in [
            validate_required_fields,
            validate_numeric_range,
            validate_cross_check,
            validate_negative_check,
        ]:
            results = check_fn(form)
            for r in results:
                if r["severity"] == "error":
                    errors.append(r)
                else:
                    warnings.append(r)

    return errors, warnings


# ── 远程预校验 ────────────────────────────────────────

def remote_validate(company_id: str, period: str, forms: list) -> tuple[list, list]:
    """调用税务局预校验接口"""
    result = api_call("validate_declaration", payload={
        "company_id": company_id,
        "period": period,
        "forms": forms,
    })

    if not result["ok"]:
        # 远程校验失败本身不阻断，记为 warning
        return [], [{
            "field": "_remote",
            "rule": "remote_unavailable",
            "message": f"远程预校验接口调用失败: {result['error']}",
            "severity": "warning",
            "source": "remote",
        }]

    data = result["data"]
    errors = []
    warnings = []

    for item in data.get("errors", data.get("validation_errors", [])):
        entry = {
            "field": item.get("field", "unknown"),
            "rule": item.get("rule", "remote_rule"),
            "message": item.get("message", str(item)),
            "severity": item.get("severity", "error"),
            "source": "remote",
        }
        if entry["severity"] == "error":
            errors.append(entry)
        else:
            warnings.append(entry)

    return errors, warnings


# ── 主入口 ────────────────────────────────────────────

def validate_declaration(company_id: str, period: str, forms: list) -> dict:
    # 1. 本地校验
    local_errors, local_warnings = local_validate(forms)

    # 如果本地校验有严重错误，直接返回，不调远程
    if local_errors:
        return {
            "ok": True,
            "is_valid": False,
            "errors": local_errors,
            "warnings": local_warnings,
            "error_count": len(local_errors),
            "warning_count": len(local_warnings),
            "remote_checked": False,
            "message": f"本地校验发现 {len(local_errors)} 个错误，请修正后重试",
        }

    # 2. 远程预校验
    remote_errors, remote_warnings = remote_validate(company_id, period, forms)

    all_errors = local_errors + remote_errors
    all_warnings = local_warnings + remote_warnings
    is_valid = len(all_errors) == 0

    return {
        "ok": True,
        "is_valid": is_valid,
        "errors": all_errors,
        "warnings": all_warnings,
        "error_count": len(all_errors),
        "warning_count": len(all_warnings),
        "remote_checked": True,
        "message": "校验通过" if is_valid else f"校验发现 {len(all_errors)} 个错误",
    }


if __name__ == "__main__":
    args = parse_args()
    result = validate_declaration(
        company_id=args.get("company_id", ""),
        period=args.get("period", ""),
        forms=args.get("forms", []),
    )
    output(result)
