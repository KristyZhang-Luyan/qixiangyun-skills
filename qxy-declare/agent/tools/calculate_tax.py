#!/usr/bin/env python3
"""
calculate_tax — 税费计提计算（纯确定性，禁止 LLM）

只做三个税种：
1. 增值税 — 小规模纳税人（月报/季报）
2. 增值税 — 一般纳税人（月报）
3. 企业所得税（月/季度预缴）
附加税费基于增值税自动计算。

税率依据（2026年1月1日起施行的增值税法 + 现行有效政策）：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
增值税 - 小规模纳税人:
  · 法定征收率: 3%
  · 优惠征收率: 减按 1%（财政部 税务总局公告2023年第19号，至2027.12.31）
  · 起征点: 月 ≤ 10万 / 季 ≤ 30万 免征（普票部分）
  · 500万年销售额为小规模/一般人分界

增值税 - 一般纳税人:
  · 13% / 9% / 6%，应纳 = 销项 - 进项 - 上期留抵

企业所得税:
  · 标准 25%
  · 小型微利: 应纳税所得额×25%×20% = 实际5%
    (年应纳税所得额≤300万, 人数≤300, 资产≤5000万, 至2027.12.31)

附加税费（基于增值税）:
  · 城建税 7%/5%/1% + 教育费附加 3% + 地方教育附加 2%
  · 小规模+小微: 六税两费减半（至2027.12.31）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from decimal import Decimal, ROUND_HALF_UP
from shared import output, parse_args, log


def d(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or 0))

def r2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── 增值税 小规模 ─────────────────────────────────────

def calc_vat_small(data: dict, report_cycle: str = "quarter") -> dict:
    sales = d(data.get("sales_amount", 0))
    exempt = d(data.get("exempt_sales", 0))
    special = d(data.get("special_sales", 0))  # 开专票部分

    taxable = sales - exempt
    threshold = Decimal("300000") if report_cycle == "quarter" else Decimal("100000")
    ordinary = taxable - special

    if taxable <= threshold:
        # 未超起征点：普票免征，专票按1%
        special_tax = r2(special * Decimal("0.01"))
        return {
            "tax_code": "VAT", "tax_name": "增值税（小规模）",
            "report_cycle": report_cycle,
            "sales_amount": float(sales), "taxable_amount": float(taxable),
            "threshold": float(threshold), "below_threshold": True,
            "ordinary_sales": float(ordinary), "ordinary_tax": 0,
            "special_sales": float(special), "special_tax": float(special_tax),
            "rate": 0.01, "rate_note": "法定3%，减按1%",
            "final_amount": float(special_tax),
            "note": f"销售额 {taxable} ≤ 起征点 {threshold}，普票免征" if ordinary > 0 else "未超起征点",
        }

    # 超起征点：全部按1%
    tax = r2(taxable * Decimal("0.01"))
    return {
        "tax_code": "VAT", "tax_name": "增值税（小规模）",
        "report_cycle": report_cycle,
        "sales_amount": float(sales), "taxable_amount": float(taxable),
        "threshold": float(threshold), "below_threshold": False,
        "rate": 0.01, "rate_note": "法定3%，减按1%",
        "tax_payable": float(tax), "final_amount": float(tax),
    }


# ── 增值税 一般纳税人 ─────────────────────────────────

def calc_vat_general(data: dict) -> dict:
    output_tax = d(data.get("output_tax", 0))
    input_tax = d(data.get("input_tax", 0))
    transfer = d(data.get("input_transfer", 0))  # 进项转出
    prev_credit = d(data.get("prev_credit", 0))

    net_input = input_tax - transfer
    payable = output_tax - net_input - prev_credit
    credit_forward = Decimal("0")

    if payable < 0:
        credit_forward = abs(payable)
        payable = Decimal("0")

    return {
        "tax_code": "VAT", "tax_name": "增值税（一般纳税人）",
        "report_cycle": "month",
        "output_tax": float(output_tax),
        "input_tax": float(input_tax), "input_transfer": float(transfer),
        "net_input": float(net_input), "prev_credit": float(prev_credit),
        "tax_payable": float(r2(payable)),
        "credit_forward": float(r2(credit_forward)),
        "final_amount": float(r2(payable)),
    }


# ── 企业所得税 季度预缴 ──────────────────────────────

def calc_cit(data: dict) -> dict:
    revenue = d(data.get("revenue", 0))
    cost = d(data.get("cost", 0))
    profit = d(data.get("profit", 0)) or (revenue - cost)
    accumulated = d(data.get("accumulated_profit", 0)) or profit
    prepaid = d(data.get("prepaid_tax", 0))

    # 判断小型微利
    is_small = data.get("is_small_profit")
    if is_small is None:
        employees = data.get("employees", 0)
        total_assets = d(data.get("total_assets", 0))
        is_small = (
            accumulated <= Decimal("3000000")
            and (employees <= 300 if employees else True)
            and (total_assets <= Decimal("5000") if total_assets else True)
        )

    if accumulated <= 0:
        return {
            "tax_code": "CIT", "tax_name": "企业所得税",
            "profit": float(profit), "accumulated_profit": float(accumulated),
            "is_small_profit": is_small,
            "effective_rate": 0, "tax_payable": 0,
            "prepaid_tax": float(prepaid), "final_amount": 0,
            "note": "累计利润 ≤ 0，本期无需预缴",
        }

    if is_small:
        rate = Decimal("0.05")  # 25% × 20% = 5%
        note = "小型微利企业: 应纳税所得额×25%×20%，实际税负5%"
    else:
        rate = Decimal("0.25")
        note = "标准税率25%"

    tax = r2(accumulated * rate)
    final = max(r2(tax - prepaid), Decimal("0"))

    return {
        "tax_code": "CIT", "tax_name": "企业所得税",
        "profit": float(profit), "accumulated_profit": float(accumulated),
        "is_small_profit": is_small,
        "effective_rate": float(rate), "tax_payable": float(tax),
        "prepaid_tax": float(prepaid), "final_amount": float(final),
        "note": note,
    }


# ── 附加税费 ─────────────────────────────────────────

def calc_surcharge(vat_payable: Decimal, is_small: bool = True,
                   location: str = "city") -> dict:
    if vat_payable <= 0:
        return {"tax_code": "SURCHARGE", "tax_name": "附加税费",
                "base_amount": 0, "final_amount": 0}

    urban_rate = {"city": Decimal("0.07"), "county": Decimal("0.05"),
                  "other": Decimal("0.01")}.get(location, Decimal("0.07"))

    urban = r2(vat_payable * urban_rate)
    edu = r2(vat_payable * Decimal("0.03"))
    local_edu = r2(vat_payable * Decimal("0.02"))

    if is_small:  # 六税两费减半
        urban = r2(urban / 2)
        edu = r2(edu / 2)
        local_edu = r2(local_edu / 2)

    total = urban + edu + local_edu
    return {
        "tax_code": "SURCHARGE", "tax_name": "附加税费",
        "base_amount": float(vat_payable),
        "urban_maintenance": float(urban), "urban_rate": float(urban_rate),
        "education_surcharge": float(edu),
        "local_education_surcharge": float(local_edu),
        "half_exemption": is_small, "location": location,
        "final_amount": float(total),
    }


# ── 主入口 ────────────────────────────────────────────

CODE_MAP = {
    "VAT": "VAT",
    "CIT": "CIT",
    "CORPORATE_INCOME_TAX": "CIT",
    "BDA0610606": "VAT",   # 增值税及附加税费（小规模纳税人）
    "BDA0610100": "CIT",   # 企业所得税（季报）
    "BDA0610101": "CIT",   # 企业所得税（月报）
    "BDA0610600": "VAT",   # 增值税（一般纳税人）
    "BDA0610601": "VAT",   # 增值税及附加税费（一般纳税人）
    "BDA0620200": "VAT",   # 增值税（小规模纳税人）
}


def calculate_tax(declaration_data: dict, company_type: str = "small_scale",
                  report_cycle: str = "quarter", tax_codes: list = None,
                  **kwargs) -> dict:
    is_small = company_type == "small_scale"
    results = []
    total = Decimal("0")
    vat_payable = Decimal("0")

    if not tax_codes:
        tax_codes = ["VAT", "CIT"]

    seen = set()
    for code in tax_codes:
        normalized = CODE_MAP.get(code, CODE_MAP.get(code.upper(), code.upper()))
        if normalized in seen:
            continue
        seen.add(normalized)

        if normalized == "VAT":
            vat_data = declaration_data.get("vat", {})
            r = calc_vat_small(vat_data, report_cycle) if is_small else calc_vat_general(vat_data)
            vat_payable = d(r["final_amount"])
            results.append(r)
        elif normalized == "CIT":
            r = calc_cit(declaration_data.get("cit", {}))
            results.append(r)
        else:
            log.warning(f"未支持的税种: {code}（映射为 {normalized}），跳过")

    # 附加税
    if vat_payable > 0:
        surcharge = calc_surcharge(vat_payable, is_small,
                                   declaration_data.get("location", "city"))
        results.append(surcharge)

    for r in results:
        total += d(r.get("final_amount", 0))

    return {
        "ok": True,
        "results": results,
        "is_all_zero": total == 0,
        "total_payable": float(r2(total)),
        "summary": {
            "tax_count": len(results),
            "total_payable": float(r2(total)),
            "is_all_zero": total == 0,
            "company_type": company_type,
            "report_cycle": report_cycle,
        },
    }


if __name__ == "__main__":
    args = parse_args()
    result = calculate_tax(
        declaration_data=args.get("declaration_data", {}),
        company_type=args.get("company_type", "small_scale"),
        report_cycle=args.get("report_cycle", "quarter"),
        tax_codes=args.get("tax_codes"),
    )
    output(result)
