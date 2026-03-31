#!/usr/bin/env python3
"""
calculate_tax — 税费计提（从初始化返回的 zbGrid 节点取值，不自算）

核心逻辑：
  税局通过初始化接口已经算好了所有税额，我们只需要从返回的 zbGrid 数据中
  按照 ewblxh（外部报联序号）提取对应字段，组装成展示给用户的结构。

数据来源：
  state["data"]["init_data"]["results"] 中每个税种的 init_data 包含 zbGrid 节点，
  zbGrid 是一个列表，每项有 ewblxh 字段标识类别：
    ewblxh=1 → 一般项目（增值税一般人）/ 第1列（小规模）
    ewblxh=2 → 第2列（小规模）
    ewblxh=3 → 即征即退项目（一般人）

字段取值规则完全按照 Excel「税费计提规则」Sheet 定义。

限制行业名单（不能享受小微企业优惠）：
  烟草制品业、银行业、证券业、保险业、信托业、期货业、
  房地产开发经营、煤炭开采、黑色金属冶炼、有色金属冶炼、基础化工、
  造纸、印染、电镀、皮革、烟花爆竹、民爆
"""

from shared import output, parse_args, log


RESTRICTED_INDUSTRIES = [
    "烟草制品业",
    "银行业", "证券业", "保险业", "信托业", "期货业",
    "房地产开发经营",
    "煤炭开采", "黑色金属冶炼", "有色金属冶炼", "基础化工",
    "造纸", "印染", "电镀", "皮革",
    "烟花爆竹", "民爆",
]

INDUSTRY_TAX_BURDEN = {
    "烟草制品业": (7.0, 10.0), "电力、热力生产": (5.0, 8.0),
    "石油加工、炼焦": (4.0, 6.0), "医药制造业": (4.5, 7.0),
    "农副食品加工": (3.5, 5.0), "纺织": (3.0, 4.5), "服装": (3.0, 4.5),
    "木材、竹制品": (3.0, 4.5), "通用设备": (3.5, 5.5), "专用设备": (3.5, 5.5),
    "计算机": (2.5, 4.0), "电子制造": (2.5, 4.0),
    "批发和零售业": (0.8, 2.0), "批发": (0.8, 2.0), "零售": (1.0, 2.5),
    "建筑业": (2.0, 3.5), "房地产开发": (3.0, 4.5),
    "交通运输": (2.0, 3.0), "物流": (4.0, 6.0),
    "软件": (3.0, 5.0), "信息技术": (3.0, 5.0),
    "租赁": (4.0, 6.0), "商务服务": (5.0, 7.0), "咨询": (5.0, 7.0),
    "餐饮": (2.0, 4.0), "住宿": (2.0, 4.0),
}


def _sf(val, default=0.0):
    if val is None: return default
    try: return float(val)
    except (ValueError, TypeError): return default


def _get_zb_grid(init_data):
    if not isinstance(init_data, dict): return []
    for path in [init_data, init_data.get("data", {}), init_data.get("data", {}).get("data", {})]:
        if isinstance(path, dict):
            g = path.get("zbGrid", path.get("zb_grid", []))
            if isinstance(g, list) and g: return g
    return []


def _row(zb_grid, ewblxh):
    for r in zb_grid:
        if isinstance(r, dict):
            try:
                if int(r.get("ewblxh", r.get("EWBLXH", -1))) == ewblxh: return r
            except (TypeError, ValueError): pass
    return {}


def _f(row, name): return _sf(row.get(name, row.get(name.upper(), 0)))


def _sum(zb_grid, ids, name):
    return sum(_f(_row(zb_grid, i), name) for i in ids)


def _is_restricted(industry):
    if not industry: return False
    return any(r in industry for r in RESTRICTED_INDUSTRIES)


def _burden_status(rate, industry):
    if not industry or rate == 0: return ""
    for kw, (lo, hi) in INDUSTRY_TAX_BURDEN.items():
        if kw in industry:
            return "偏低" if rate < lo else ("偏高" if rate > hi else "正常")
    return ""


def extract_vat_general(init_data, industry=""):
    zb = _get_zb_grid(init_data)
    sales = sum(_sum(zb, [1, 3], f) for f in ["asysljsxse", "ajybfjsxse", "mdtbfckxse", "msxse"])
    output_tax = _sum(zb, [1, 3], "xxse")
    input_tax = _sum(zb, [1, 3], "jxse")
    input_transfer = _sum(zb, [1, 3], "jxsezc")
    vat_payable = _sum(zb, [1, 3], "bqybtse")
    r1 = _row(zb, 1)
    urban = _f(r1, "bqybtsecjs")
    edu = _f(r1, "bqybtsejyfj")
    local_edu = _f(r1, "bqybtsedfjyfj")
    surcharge = urban + edu + local_edu
    total = vat_payable + surcharge
    rate = (total / sales * 100) if sales > 0 else 0
    return {
        "tax_code": "VAT", "tax_name": "增值税（一般纳税人）", "taxpayer_type": "general",
        "sales_revenue": round(sales, 2), "output_tax": round(output_tax, 2),
        "input_tax": round(input_tax, 2), "input_transfer": round(input_transfer, 2),
        "vat_payable": round(vat_payable, 2),
        "urban_maintenance_tax": round(urban, 2), "education_surcharge": round(edu, 2),
        "local_education_surcharge": round(local_edu, 2), "surcharge_total": round(surcharge, 2),
        "total_payable": round(total, 2),
        "tax_burden_rate": round(rate, 4), "burden_status": _burden_status(rate, industry),
        "final_amount": round(total, 2),
    }


def extract_vat_small(init_data, report_cycle="quarter", industry=""):
    zb = _get_zb_grid(init_data)
    sales = sum(_sum(zb, [1, 2], f) for f in ["yzzzsbhsxse", "xsczbdcbhsxse", "msxse", "ckmsxse"])
    taxable = sum(_sum(zb, [1, 2], f) for f in ["yzzzsbhsxse", "xsczbdcbhsxse"])
    exempt = sum(_sum(zb, [1, 2], f) for f in ["msxse", "ckmsxse"])
    tax_due = _sum(zb, [1, 2], "ynsehj")
    reduction = _sum(zb, [1, 2], "bqynsejze")
    vat_payable = _sum(zb, [1, 2], "bqybtse")
    r1 = _row(zb, 1)
    urban = _f(r1, "bqybtsecjs")
    edu = _f(r1, "bqybtsejyfj")
    local_edu = _f(r1, "bqybtsedfjyfj")
    surcharge = urban + edu + local_edu
    total = vat_payable + surcharge
    threshold = 300000 if report_cycle == "quarter" else 100000
    rate = (total / sales * 100) if sales > 0 else 0
    return {
        "tax_code": "VAT", "tax_name": "增值税（小规模纳税人）", "taxpayer_type": "small_scale",
        "report_cycle": report_cycle,
        "sales_revenue": round(sales, 2), "taxable_revenue": round(taxable, 2),
        "exempt_revenue": round(exempt, 2),
        "tax_due": round(tax_due, 2), "tax_reduction": round(reduction, 2),
        "vat_payable": round(vat_payable, 2),
        "below_threshold": sales <= threshold, "threshold": threshold,
        "urban_maintenance_tax": round(urban, 2), "education_surcharge": round(edu, 2),
        "local_education_surcharge": round(local_edu, 2), "surcharge_total": round(surcharge, 2),
        "total_payable": round(total, 2),
        "tax_burden_rate": round(rate, 4), "burden_status": _burden_status(rate, industry),
        "final_amount": round(total, 2),
    }


def extract_cit(init_data, industry="", employees=0, total_assets=0,
                loss_offset=0, financial_report=None):
    revenue = cost = expenses = profit = 0.0
    source = "invoice"

    if financial_report and isinstance(financial_report, dict):
        source = "financial_report"
        items = financial_report.get("items", financial_report.get("data", []))
        if isinstance(items, list):
            for it in items:
                nm = it.get("name", "")
                v = _sf(it.get("value2", it.get("value", 0)))
                if "营业收入" in nm and "一" in nm: revenue = v
                elif "营业成本" in nm: cost = v
                elif "销售费用" in nm: expenses += v
                elif "管理费用" in nm: expenses += v
                elif "财务费用" in nm: expenses += v
                elif "利润总额" in nm: profit = v
        if profit == 0 and revenue > 0: profit = revenue - cost - expenses
    else:
        zb = _get_zb_grid(init_data)
        for f in ["asysljsxse", "ajybfjsxse", "mdtbfckxse", "msxse"]:
            revenue += _sum(zb, [1, 3], f)
        if revenue == 0:
            for f in ["yzzzsbhsxse", "xsczbdcbhsxse", "msxse", "ckmsxse"]:
                revenue += _sum(zb, [1, 2], f)
        profit = revenue - cost - expenses

    if loss_offset > 0 and profit > loss_offset:
        taxable_income = profit - loss_offset
    elif loss_offset > 0:
        taxable_income = 0
    else:
        taxable_income = max(profit, 0)

    cit_due = taxable_income * 0.25 if taxable_income > 0 else 0
    is_small = (not _is_restricted(industry)
                and taxable_income <= 3000000
                and (employees <= 300 if employees > 0 else True)
                and (total_assets <= 50000000 if total_assets > 0 else True))
    reduction = taxable_income * 0.20 if is_small else 0
    final = max(cit_due - reduction, 0)

    return {
        "tax_code": "CIT", "tax_name": "企业所得税", "data_source": source,
        "revenue": round(revenue, 2), "cost": round(cost, 2), "expenses": round(expenses, 2),
        "profit": round(profit, 2), "loss_offset": round(loss_offset, 2),
        "taxable_income": round(taxable_income, 2), "cit_due": round(cit_due, 2),
        "is_restricted_industry": _is_restricted(industry), "is_small_profit": is_small,
        "small_profit_reduction": round(reduction, 2), "final_amount": round(final, 2),
    }


CODE_MAP = {
    "BDA0610606": "VAT_SMALL", "BDA0620200": "VAT_SMALL",
    "BDA0610600": "VAT_GENERAL", "BDA0610601": "VAT_GENERAL",
    "BDA0611159": "CIT", "BDA0610100": "CIT", "BDA0610101": "CIT",
    "VAT": "VAT_SMALL", "CIT": "CIT",
}


def calculate_tax(declaration_data=None, company_type="small_scale",
                  report_cycle="quarter", tax_codes=None,
                  init_data=None, industry="",
                  employees=0, total_assets=0, loss_offset=0,
                  financial_report=None, **kwargs):
    results, total = [], 0.0
    if not tax_codes: tax_codes = ["VAT", "CIT"]

    init_results = {}
    if init_data and isinstance(init_data, dict):
        for item in init_data.get("results", []):
            init_results[item.get("tax_code", "")] = item.get("init_data", {})

    seen = set()
    for code in tax_codes:
        norm = CODE_MAP.get(code, CODE_MAP.get(code.upper(), ""))
        if not norm or norm in seen: continue
        seen.add(norm)
        ci = init_results.get(code, {})

        if norm == "VAT_SMALL":
            results.append(extract_vat_small(ci, report_cycle, industry))
        elif norm == "VAT_GENERAL":
            results.append(extract_vat_general(ci, industry))
        elif norm == "CIT":
            results.append(extract_cit(ci, industry, employees, total_assets, loss_offset, financial_report))

    for r in results: total += r.get("final_amount", 0)

    return {
        "ok": True, "results": results,
        "is_all_zero": total == 0, "total_payable": round(total, 2),
        "summary": {"tax_count": len(results), "total_payable": round(total, 2),
                     "is_all_zero": total == 0, "company_type": company_type,
                     "report_cycle": report_cycle},
    }


if __name__ == "__main__":
    args = parse_args()
    result = calculate_tax(
        declaration_data=args.get("declaration_data", {}),
        company_type=args.get("company_type", "small_scale"),
        report_cycle=args.get("report_cycle", "quarter"),
        tax_codes=args.get("tax_codes"),
        init_data=args.get("init_data"),
        industry=args.get("industry", ""),
        employees=int(args.get("employees", 0)),
        total_assets=float(args.get("total_assets", 0)),
        loss_offset=float(args.get("loss_offset", 0)),
        financial_report=args.get("financial_report"),
    )
    output(result)
