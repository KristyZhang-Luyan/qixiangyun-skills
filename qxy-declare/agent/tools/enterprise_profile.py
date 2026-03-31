#!/usr/bin/env python3
"""
enterprise_profile — 企业画像（数据采集 + 获取全量数据）
对应企享云接口:
  MCP URL: https://mcp.qixiangyun.com/mcp/enterprise_profiling_service-http
  1. 发起: initiate_enterprise_data_collection_auto
  2. 轮询: get_collection_status_and_full_data_auto → 采集完成

企业画像规则（来自Excel「企业画像规则」Sheet）:

一、企业基础身份画像（来源: 发票统计数据接口 jcxx 节点）
  - nsrmc:   企业名称
  - nslxdm:  纳税人类型
  - nsztmc:  税务经营状态
  - sshymc:  所属行业
  - xydj:    信用等级
  - sjjyys:  实际经营月数

二、近3年经营大盘画像（来源: 发票统计数据接口 开票/采购汇总）
  - totalInvoiceAmt:          近3年累计总营收（不含税）— 24个月汇总
  - validTransWithouttaxAmt:  近3年累计采购成本（不含税）— 24个月汇总
  - productName:              核心赚钱业务TOP1 — 按商品名称汇总取最高金额

四、近3年发票健康画像
  - invoiceNum:               3年累计开票总笔数（销项）— 24个月汇总
  - validTransInvoiceNum:     3年累计收票总笔数（进项）— 24个月汇总
  - 销项发票开票频率:           validTransInvoiceNum / 24 月

五、近3年税务申报健康画像（来源: 税务统计数据接口）
  - qsxx节点有值:             当前是否存在欠税 → 是/否
  - three_year_vat_declare_count: 3年增值税申报次数
  - tax_credit_grade:         税务信用基础等级（A/B=良好, M=一般, C/D=偏低）
  - wfxx节点有值:             3年内是否存在违法信息 → 是/否
  - sjje:                     3年缴款总金额（汇总）
  - jkfsrq + sjje:            缴款金额最大的年月
"""

from shared import api_call, poll_task, output, parse_args, log


def _parse_profile_data(raw_data: dict) -> dict:
    """
    从MCP返回的全量数据中，按照Excel企业画像规则提取结构化画像。
    """
    if not isinstance(raw_data, dict):
        return {"raw": raw_data}

    data = raw_data.get("data", raw_data)

    # 一、企业基础身份画像 (jcxx 节点)
    jcxx = data.get("jcxx", data.get("basicInfo", {}))
    if not isinstance(jcxx, dict):
        jcxx = {}

    basic_profile = {
        "enterprise_name": jcxx.get("nsrmc", ""),
        "taxpayer_type": jcxx.get("nslxdm", ""),
        "tax_status": jcxx.get("nsztmc", ""),
        "industry": jcxx.get("sshymc", ""),
        "credit_grade": jcxx.get("xydj", ""),
        "operating_months": jcxx.get("sjjyys", 0),
    }

    # 二、近3年经营大盘画像 (开票/采购汇总, 24个月数据)
    invoice_summary = data.get("invoiceSummary", data.get("kphzxx", []))
    purchase_summary = data.get("purchaseSummary", data.get("cgspxx", []))
    sales_summary = data.get("salesSummary", data.get("xsspxx", []))

    total_revenue = 0
    total_invoice_num = 0
    if isinstance(invoice_summary, list):
        for item in invoice_summary:
            total_revenue += float(item.get("totalInvoiceAmt", 0) or 0)
            total_invoice_num += int(item.get("invoiceNum", 0) or 0)

    total_purchase_cost = 0
    total_purchase_num = 0
    if isinstance(purchase_summary, list):
        for item in purchase_summary:
            total_purchase_cost += float(item.get("validTransWithouttaxAmt", 0) or 0)
            total_purchase_num += int(item.get("validTransInvoiceNum", 0) or 0)

    # 核心赚钱业务TOP1
    product_amounts = {}
    sales_invoice_num = 0
    if isinstance(sales_summary, list):
        for item in sales_summary:
            name = item.get("productName", "")
            amt = float(item.get("totalInvoiceAmt", item.get("validTransWithouttaxAmt", 0)) or 0)
            sales_invoice_num += int(item.get("validTransInvoiceNum", item.get("invoiceNum", 0)) or 0)
            if name:
                product_amounts[name] = product_amounts.get(name, 0) + amt

    top_product = ""
    if product_amounts:
        top_product = max(product_amounts, key=product_amounts.get)

    business_profile = {
        "total_revenue_3y": total_revenue,
        "total_purchase_cost_3y": total_purchase_cost,
        "top_business": top_product,
    }

    # 四、近3年发票健康画像
    month_count = max(len(invoice_summary) if isinstance(invoice_summary, list) else 1, 1)
    invoice_health = {
        "total_sales_invoices_3y": total_invoice_num,
        "total_purchase_invoices_3y": total_purchase_num,
        "avg_monthly_sales_invoices": round(sales_invoice_num / month_count, 1) if month_count else 0,
    }

    # 五、近3年税务申报健康画像
    tax_health_data = data.get("taxHealth", data.get("swsb", {}))
    if not isinstance(tax_health_data, dict):
        tax_health_data = {}

    has_overdue_tax = bool(data.get("qsxx", tax_health_data.get("qsxx")))
    has_violations = bool(data.get("wfxx", tax_health_data.get("wfxx")))
    vat_declare_count = tax_health_data.get("three_year_vat_declare_count", 0)

    credit_grade = tax_health_data.get("tax_credit_grade", jcxx.get("xydj", ""))
    if credit_grade in ("A", "B"):
        credit_label = "税务信用良好"
    elif credit_grade == "M":
        credit_label = "信用一般"
    elif credit_grade in ("C", "D"):
        credit_label = "信用偏低"
    else:
        credit_label = credit_grade or "未知"

    # 3年缴款总金额 & 缴款金额最大的年月
    payment_records = data.get("skzsxx", data.get("paymentRecords", []))
    total_paid = 0
    monthly_paid = {}
    if isinstance(payment_records, list):
        for rec in payment_records:
            amt = float(rec.get("sjje", 0) or 0)
            total_paid += amt
            pay_date = str(rec.get("jkfsrq", ""))
            ym = pay_date[:7] if len(pay_date) >= 7 else pay_date
            if ym:
                monthly_paid[ym] = monthly_paid.get(ym, 0) + amt

    max_payment_month = ""
    if monthly_paid:
        max_payment_month = max(monthly_paid, key=monthly_paid.get)

    tax_health = {
        "has_overdue_tax": has_overdue_tax,
        "vat_declare_count_3y": vat_declare_count,
        "credit_grade": credit_grade,
        "credit_label": credit_label,
        "has_violations": has_violations,
        "total_paid_3y": total_paid,
        "max_payment_month": max_payment_month,
    }

    return {
        "basic": basic_profile,
        "business": business_profile,
        "invoice_health": invoice_health,
        "tax_health": tax_health,
    }


def enterprise_profile(agg_org_id: str, nsrsbh: str = "", area_code: str = "",
                       cjyfq: str = "", cjyfz: str = "") -> dict:
    """
    获取企业画像全量数据
    Args:
        agg_org_id: 企业聚合ID
        nsrsbh: 纳税人识别号（必填）
        area_code: 地区代码（必填）
        cjyfq: 采集月份起，如 "202401"（必填）
        cjyfz: 采集月份止，如 "202603"（必填）
    Returns:
        {ok, profile, raw_data}
    """
    # 1. 发起企业数据采集
    log.info(f"[企业画像] 发起数据采集: {agg_org_id}")
    payload = {"aggOrgId": agg_org_id}
    if nsrsbh:
        payload["nsrsbh"] = nsrsbh
    if area_code:
        payload["areaCode"] = area_code
    if cjyfq:
        payload["cjyfq"] = cjyfq
    if cjyfz:
        payload["cjyfz"] = cjyfz
    result = api_call("initiate_enterprise_data_collection", payload=payload)

    if not result["ok"]:
        return {
            "ok": False,
            "error": result.get("error", result.get("message", "发起企业数据采集失败")),
            "code": result.get("code"),
        }

    # 提取 taskId
    data = result["data"]
    task_id = data.get("data", {}).get("taskId", data.get("taskId"))
    if not task_id:
        # 有些接口直接返回全量数据，不需要轮询
        profile = _parse_profile_data(data)
        return {
            "ok": True,
            "profile": profile,
            "raw_data": data,
        }

    # 2. 轮询获取采集状态及全量数据
    log.info(f"[企业画像] 轮询采集结果: taskId={task_id}")
    poll_extra = {}
    if nsrsbh:
        poll_extra["nsrsbh"] = nsrsbh
    poll_result = poll_task(agg_org_id, task_id, extra_args=poll_extra or None)

    if not poll_result["ok"]:
        return {
            "ok": False,
            "error": poll_result.get("error"),
            "status": poll_result.get("status"),
        }

    # 3. 解析画像数据
    raw_data = poll_result.get("data", {})
    profile = _parse_profile_data(raw_data)

    return {
        "ok": True,
        "profile": profile,
        "raw_data": raw_data,
    }


if __name__ == "__main__":
    args = parse_args()
    result = enterprise_profile(
        agg_org_id=str(args.get("agg_org_id", args.get("aggOrgId", ""))),
    )
    output(result)
