#!/usr/bin/env python3
"""
demo_flow.py — 六步演示流程脚本

严格按照演示步骤执行：
  第一步：登录
  第二步：企业画像（005）
  第三步：获取清册（001-005）
  第四步：财务报表Excel导入申报 + 财报申报提交（007，小企业会计准则）
  第五步：企业所得税A初始化 + 企业所得税A申报提交（006）
  第六步：增值税批量初始化（001-005）
          + 增值税批量申报提交（001-005）
          + PDF下载（005）+ 视频直播（005）+ 缴款提交（005）+ 完税凭证下载（005）

用法：
  python3 demo_flow.py '{"action":"step1"}'
  python3 demo_flow.py '{"action":"step2"}'
  python3 demo_flow.py '{"action":"step3"}'
  python3 demo_flow.py '{"action":"step4","file_path":"/path/to/file.xlsx"}'
  python3 demo_flow.py '{"action":"step5"}'
  python3 demo_flow.py '{"action":"step6_vat_init"}'
  python3 demo_flow.py '{"action":"step6_vat_submit"}'
  python3 demo_flow.py '{"action":"step6_pdf"}'
  python3 demo_flow.py '{"action":"step6_video"}'
  python3 demo_flow.py '{"action":"step6_payment"}'
  python3 demo_flow.py '{"action":"step6_certificate"}'
  python3 demo_flow.py '{"action":"run_all","file_path":"/path/to/file.xlsx"}'
"""

import json
import sys
import os
import calendar

sys.path.insert(0, "/Users/kristyzhang/.openclaw/agents/qxy-declare/agent/tools")

from shared import output, log, api_call, poll_task

COMPANIES = {
    "QXY100031100000001": {"name": "北京数算科技有限公司", "agg_org_id": "5208291448799296"},
    "QXY100031100000002": {"name": "北京星云智联科技有限公司", "agg_org_id": "5208295720930176"},
    "QXY100031100000003": {"name": "上海瀚海商贸有限公司", "agg_org_id": "5208296132444224"},
    "QXY100031100000004": {"name": "深圳前海新能源发展有限公司", "agg_org_id": "5208296673559936"},
    "QXY100031100000005": {"name": "天津市金万翔建材科技有限公司", "agg_org_id": "5208297141358272"},
    "QXY100031100000006": {"name": "中邮证券有限责任公司天津分公司", "agg_org_id": "5208297482143808"},
    "QXY100031100000007": {"name": "深圳交易研究院有限公司", "agg_org_id": "5208297826012864"},
}

YEAR = 2026
PERIOD = 3
LAST_DAY = calendar.monthrange(YEAR, PERIOD)[1]
SSQ_Q = f"{YEAR}-{PERIOD:02d}-01"
SSQ_Z = f"{YEAR}-{PERIOD:02d}-{LAST_DAY}"

VAT_BATCH_IDS = [
    "QXY100031100000001", "QXY100031100000002", "QXY100031100000003",
    "QXY100031100000004", "QXY100031100000005",
]

def _ci(cid): return COMPANIES.get(cid, {"name": cid, "agg_org_id": ""})
def _ok(msg): return {"ok": True, "user_message": msg}
def _err(msg): return {"ok": False, "user_message": msg}


# ══════════════════════════════════════════════════════════
# 第一步：登录
# ══════════════════════════════════════════════════════════
def step1_login():
    log.info("【第一步】登录")
    try:
        from login import ensure_logged_in
        r = ensure_logged_in()
        return _ok("第一步完成：已成功登录") if r else _err("第一步失败：登录失败")
    except Exception as e:
        return _err(f"第一步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第二步：企业画像（005）
# ══════════════════════════════════════════════════════════
def step2_enterprise_profile():
    log.info("【第二步】企业画像")
    cid = "QXY100031100000005"
    c = _ci(cid)
    try:
        from enterprise_profile import enterprise_profile
        r = enterprise_profile(c["agg_org_id"])
        if r.get("ok"):
            return _ok(f"第二步完成：{c['name']}（{cid}）企业画像采集成功")
        return _err(f"第二步失败：{r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第二步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第三步：获取清册（001-005）
# ══════════════════════════════════════════════════════════
def step3_fetch_list():
    log.info("【第三步】获取清册")
    try:
        from fetch_tax_list import fetch_tax_list
        lines = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            log.info(f"获取清册: {c['name']}")
            r = fetch_tax_list(c["agg_org_id"], YEAR, PERIOD)
            if r.get("ok"):
                items = r.get("required_items", [])
                names = [i.get("zsxmMc", i.get("yzpzzlDm", "")) for i in items]
                lines.append(f"  {c['name']}：{len(items)}个待申报税种 ({', '.join(names)})")
            else:
                lines.append(f"  {c['name']}：获取失败 - {r.get('error', '未知错误')}")
        return _ok(f"第三步完成：5家企业清册获取完毕\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第三步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第四步：财务报表Excel导入申报（007，小企业会计准则）
# ══════════════════════════════════════════════════════════
def step4_financial_report(file_path=""):
    log.info("【第四步】财务报表Excel导入申报 + 财报申报提交")
    cid = "QXY100031100000007"
    c = _ci(cid)
    if not file_path:
        return _ok(f"第四步待执行：{c['name']}（{cid}）需要上传财务报表Excel文件。\n\n"
                   f"请提供 file_path 参数，例如：\n"
                   f'python3 demo_flow.py \'{{"action":"step4","file_path":"/path/to/财务报表.xlsx"}}\'')
    try:
        import base64
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        payload = {
            "aggOrgId": c["agg_org_id"],
            "year": YEAR,
            "period": PERIOD,
            "isDirectDeclare": True,
            "yzpzzlDm": "CWBBSB",
            "zlbsxlDm": "ZL1001003",
            "templateCode": "0",
            "ssqQ": SSQ_Q,
            "ssqZ": SSQ_Z,
            "fileBase64": base64.b64encode(file_bytes).decode("utf-8"),
            "fileName": os.path.basename(file_path),
        }
        log.info(f"上传财务报表: {payload['fileName']}")
        r = api_call("upload_financial_report_excel", payload=payload)
        if not r.get("ok"):
            return _err(f"第四步失败：上传失败 - {r.get('error', r.get('message'))}")
        data = r.get("data", {})
        tid = (data.get("data") or {}).get("taskId", data.get("taskId"))
        if tid:
            pr = poll_task(c["agg_org_id"], tid, result_endpoint="query_financial_report_result")
            if pr.get("ok") and pr.get("status") == "completed":
                return _ok(f"第四步完成：{c['name']}（{cid}）财务报表申报成功")
            return _err(f"第四步失败：{pr.get('error', '状态异常')}")
        return _ok(f"第四步完成：{c['name']}（{cid}）财务报表上传成功")
    except Exception as e:
        return _err(f"第四步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第五步：企业所得税A初始化 + 申报提交（006）
# 注意：税种代码为 BDA0611159（A类季报），不是 BDA0610100（B类）
# ══════════════════════════════════════════════════════════
def step5_cit():
    log.info("【第五步】企业所得税A初始化 + 申报提交")
    cid = "QXY100031100000006"
    c = _ci(cid)
    try:
        from init_declaration import init_declaration
        from submit_declaration import submit_simplified

        # 初始化：企业所得税A类（BDA0611159）
        log.info(f"企业所得税A初始化: {c['name']}")
        ir = init_declaration(c["agg_org_id"], YEAR, PERIOD, [{"yzpzzlDm": "BDA0611159"}])
        if not ir.get("ok") and not ir.get("results"):
            return _err(f"第五步失败：初始化失败 - {ir.get('errors', '未知错误')}")

        # 申报提交
        log.info(f"企业所得税A申报提交: {c['name']}")
        sr = submit_simplified(c["agg_org_id"], YEAR, PERIOD, sb_init=True)
        if sr.get("ok"):
            return _ok(f"第五步完成：{c['name']}（{cid}）企业所得税A初始化并申报成功")
        return _err(f"第五步失败：申报提交失败 - {sr.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第五步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第六步-a：增值税批量初始化（001-005）
# ══════════════════════════════════════════════════════════
def step6_vat_init():
    log.info("【第六步】增值税批量初始化")
    try:
        from init_declaration import init_declaration
        lines = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            log.info(f"增值税初始化: {c['name']}")
            ir = init_declaration(c["agg_org_id"], YEAR, PERIOD, [{"yzpzzlDm": "BDA0610606"}])
            ok = ir.get("ok") or bool(ir.get("results"))
            status = "成功" if ok else f"失败 - {ir.get('errors', '未知错误')}"
            lines.append(f"  {c['name']}：初始化{status}")
        return _ok(f"第六步（批量初始化）完成：\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第六步（批量初始化）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第六步-b：增值税批量申报提交（001-005）
# ══════════════════════════════════════════════════════════
def step6_vat_submit():
    log.info("【第六步】增值税批量申报提交")
    try:
        from submit_declaration import submit_simplified
        lines = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            log.info(f"增值税申报提交: {c['name']}")
            sr = submit_simplified(c["agg_org_id"], YEAR, PERIOD, sb_init=True)
            status = "成功" if sr.get("ok") else f"失败 - {sr.get('error', '未知错误')}"
            lines.append(f"  {c['name']}：申报{status}")
        return _ok(f"第六步（批量申报提交）完成：\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第六步（批量申报提交）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第六步-c：PDF下载（005）
# ══════════════════════════════════════════════════════════
def step6_pdf():
    log.info("【第六步】增值税PDF下载")
    cid = "QXY100031100000005"
    c = _ci(cid)
    try:
        from download_receipt import download_receipt
        r = download_receipt(c["agg_org_id"], YEAR, PERIOD, [{
            "yzpzzlDm": "BDA0610606",
            "ssqQ": SSQ_Q,
            "ssqZ": SSQ_Z,
        }])
        if r.get("ok"):
            # 尝试从多个可能的字段提取 PDF URL
            pdf_url = ""
            pdf_data = r.get("pdf_data", {})
            structured = r.get("structured_data", {})
            for source in [structured, pdf_data]:
                if not isinstance(source, dict):
                    continue
                # 直接字段
                for key in ("pdfFileUrl", "pdfUrl", "fileUrl", "url"):
                    if source.get(key):
                        pdf_url = source[key]
                        break
                if pdf_url:
                    break
                # 嵌套在 detail/zsxmList/list 中
                for container_key in ("detail", "zsxmList", "list", "data"):
                    items = source.get(container_key, [])
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                for key in ("pdfFileUrl", "pdfUrl", "fileUrl", "url"):
                                    if item.get(key):
                                        pdf_url = item[key]
                                        break
                            if pdf_url:
                                break
                    if pdf_url:
                        break

            msg = f"第六步（PDF下载）完成：{c['name']}（{cid}）"
            if pdf_url:
                msg += f"\n\nPDF链接: {pdf_url}"
            return _ok(msg)
        return _err(f"第六步失败：PDF下载失败 - {r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第六步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第六步-d：视频直播（005）— 静态链接
# ══════════════════════════════════════════════════════════
def step6_video():
    url = ("http://qxy-oss-robot-product.qixiangyun.com/VIDEO/"
           "etax-agg-product_0d17b8be20214c11a52ccb869fb185ce_1773040951439.webm"
           "?OSSAccessKeyId=LTAI5tMHcomKiHbKRhS2uU8X&Expires=1804144951"
           "&Signature=4GzUiutzNNoMGMtL%2BCt/%2Bk9qWcY%3D")
    return _ok(f"第六步（视频直播）完成：天津市金万翔建材科技有限公司（005）\n\n申报操作视频: {url}")


# ══════════════════════════════════════════════════════════
# 第六步-e：缴款提交（005）
# ══════════════════════════════════════════════════════════
def step6_payment():
    log.info("【第六步】增值税缴款提交")
    cid = "QXY100031100000005"
    c = _ci(cid)
    try:
        from payment import execute_payment
        r = execute_payment(c["agg_org_id"], YEAR, PERIOD, [])
        if r.get("ok"):
            return _ok(f"第六步（缴款提交）完成：{c['name']}（{cid}）缴款成功")
        return _err(f"第六步失败：缴款失败 - {r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第六步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第六步-f：完税凭证下载（005）
# 注意：download_tax_certificate 签名是 (agg_org_id, zsxm_dtos)，只有2个参数
# ══════════════════════════════════════════════════════════
def step6_certificate():
    log.info("【第六步】增值税完税凭证下载")
    cid = "QXY100031100000005"
    c = _ci(cid)
    try:
        from payment import download_tax_certificate
        r = download_tax_certificate(c["agg_org_id"], [{
            "yzpzzlDm": "BDA0610606",
            "ssqQ": SSQ_Q,
            "ssqZ": SSQ_Z,
        }])
        if r.get("ok"):
            return _ok(f"第六步（完税凭证下载）完成：{c['name']}（{cid}）完税凭证下载成功")
        return _err(f"第六步失败：完税凭证下载失败 - {r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第六步失败：{e}")


# ══════════════════════════════════════════════════════════
# run_all：按顺序执行全部步骤
# ══════════════════════════════════════════════════════════
def run_all(file_path=""):
    steps = [
        ("step1",              lambda: step1_login()),
        ("step2",              lambda: step2_enterprise_profile()),
        ("step3",              lambda: step3_fetch_list()),
        ("step4",              lambda: step4_financial_report(file_path)),
        ("step5",              lambda: step5_cit()),
        ("step6_vat_init",     lambda: step6_vat_init()),
        ("step6_vat_submit",   lambda: step6_vat_submit()),
        ("step6_pdf",          lambda: step6_pdf()),
        ("step6_video",        lambda: step6_video()),
        ("step6_payment",      lambda: step6_payment()),
        ("step6_certificate",  lambda: step6_certificate()),
    ]
    results = []
    for name, fn in steps:
        log.info(f"========== 执行: {name} ==========")
        r = fn()
        results.append({"step": name, "ok": r.get("ok", False), "message": r.get("user_message", "")})
        if not r.get("ok"):
            log.warning(f"{name} 失败，继续执行下一步...")

    # 汇总
    ok_count = sum(1 for r in results if r["ok"])
    total = len(results)
    lines = []
    for r in results:
        mark = "OK" if r["ok"] else "FAIL"
        lines.append(f"  [{mark}] {r['step']}")
    summary = f"全部步骤执行完毕：{ok_count}/{total} 成功\n\n" + "\n".join(lines)
    return _ok(summary) if ok_count == total else _err(summary)


# ══════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════
ACTION_MAP = {
    "step1":             lambda a: step1_login(),
    "step2":             lambda a: step2_enterprise_profile(),
    "step3":             lambda a: step3_fetch_list(),
    "step4":             lambda a: step4_financial_report(a.get("file_path", "")),
    "step5":             lambda a: step5_cit(),
    "step6_vat_init":    lambda a: step6_vat_init(),
    "step6_vat_submit":  lambda a: step6_vat_submit(),
    "step6_pdf":         lambda a: step6_pdf(),
    "step6_video":       lambda a: step6_video(),
    "step6_payment":     lambda a: step6_payment(),
    "step6_certificate": lambda a: step6_certificate(),
    "run_all":           lambda a: run_all(a.get("file_path", "")),
}

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    action = args.get("action", "")
    if action not in ACTION_MAP:
        output({"ok": False, "user_message": f"未知操作: {action}\n可用: {', '.join(sorted(ACTION_MAP.keys()))}"})
        sys.exit(1)
    output(ACTION_MAP[action](args))
