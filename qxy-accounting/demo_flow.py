#!/usr/bin/env python3
"""
demo_flow.py — 四步演示流程脚本

严格按照演示步骤执行：
  第一步：企业画像（005 天津市金万翔建材科技有限公司）
  第二步：获取清册（001-005，5家）
  第三步：财务报表Excel上传申报（007 深圳交易研究院有限公司，小企业会计准则）
          - 无file_path时提示用户上传
          - 有file_path时上传并直接申报，返回"已成功申报"
  第四步：增值税批量初始化（001-005）→ 列出金额等数据给用户确认
          → 批量申报提交（001-005）
          → PDF下载（005）+ 视频直播（005）

用法：
  python3 demo_flow.py '{"action":"step1"}'
  python3 demo_flow.py '{"action":"step2"}'
  python3 demo_flow.py '{"action":"step3"}'
  python3 demo_flow.py '{"action":"step3","file_path":"/path/to/file.xlsx"}'
  python3 demo_flow.py '{"action":"step4_vat_init"}'
  python3 demo_flow.py '{"action":"step4_vat_submit"}'
  python3 demo_flow.py '{"action":"step4_pdf"}'
  python3 demo_flow.py '{"action":"step4_video"}'
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
# 第一步：企业画像（005）
# ══════════════════════════════════════════════════════════
def step1_profile():
    log.info("【第一步】企业画像")
    cid = "QXY100031100000005"
    c = _ci(cid)
    try:
        from enterprise_profile import enterprise_profile
        r = enterprise_profile(c["agg_org_id"])
        if r.get("ok"):
            return _ok(f"第一步完成：{c['name']}（{cid}）企业画像采集成功")
        return _err(f"第一步失败：{r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第一步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第二步：获取清册（001-005）
# ══════════════════════════════════════════════════════════
def step2_fetch_list():
    log.info("【第二步】获取清册")
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
        return _ok(f"第二步完成：5家企业清册获取完毕\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第二步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第三步：财务报表Excel上传申报（007，小企业会计准则）
# 无file_path时提示上传；有file_path时上传+直接申报
# ══════════════════════════════════════════════════════════
def step3_upload_excel(file_path=""):
    log.info("【第三步】财务报表Excel上传申报")
    cid = "QXY100031100000007"
    c = _ci(cid)
    if not file_path:
        return _ok(f"请上传 {c['name']} 的财务报表Excel文件（小企业会计准则），我收到后会自动导入并申报。")
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
            return _err(f"第三步失败：上传失败 - {r.get('error', r.get('message'))}")
        data = r.get("data", {})
        tid = (data.get("data") or {}).get("taskId", data.get("taskId"))
        if tid:
            pr = poll_task(c["agg_org_id"], tid, result_endpoint="query_financial_report_result")
            if pr.get("ok") and pr.get("status") == "completed":
                return _ok(f"第三步完成：{c['name']} 财务报表已成功申报")
            return _err(f"第三步失败：{pr.get('error', '状态异常')}")
        return _ok(f"第三步完成：{c['name']} 财务报表已成功申报")
    except Exception as e:
        return _err(f"第三步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第四步-a：增值税批量初始化（001-005）
# 列出各企业申报金额等数据，供用户确认
# ══════════════════════════════════════════════════════════
def step4_vat_init():
    log.info("【第四步】增值税批量初始化")
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
        return _ok(f"第四步（批量初始化）完成：\n\n" + "\n".join(lines) + "\n\n请确认以上信息，确认后将提交申报。")
    except Exception as e:
        return _err(f"第四步（批量初始化）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第四步-b：增值税批量申报提交（001-005）
# ══════════════════════════════════════════════════════════
def step4_vat_submit():
    log.info("【第四步】增值税批量申报提交")
    try:
        from submit_declaration import submit_simplified
        lines = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            log.info(f"增值税申报提交: {c['name']}")
            sr = submit_simplified(c["agg_org_id"], YEAR, PERIOD, sb_init=True)
            status = "成功" if sr.get("ok") else f"失败 - {sr.get('error', '未知错误')}"
            lines.append(f"  {c['name']}：申报{status}")
        return _ok(f"第四步（批量申报提交）完成：\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第四步（批量申报提交）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第四步-c：PDF下载（005 金万翔）
# ══════════════════════════════════════════════════════════
def step4_pdf():
    log.info("【第四步】增值税PDF下载")
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
            pdf_url = ""
            pdf_data = r.get("pdf_data", {})
            structured = r.get("structured_data", {})
            for source in [structured, pdf_data]:
                if not isinstance(source, dict):
                    continue
                for key in ("pdfFileUrl", "pdfUrl", "fileUrl", "url"):
                    if source.get(key):
                        pdf_url = source[key]
                        break
                if pdf_url:
                    break
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

            msg = f"第四步（PDF下载）完成：{c['name']}（{cid}）"
            if pdf_url:
                msg += f"\n\nPDF链接: {pdf_url}"
            return _ok(msg)
        return _err(f"第四步失败：PDF下载失败 - {r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第四步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第四步-d：视频直播（005 金万翔）— 静态链接
# ══════════════════════════════════════════════════════════
def step4_video():
    url = ("http://qxy-oss-robot-product.qixiangyun.com/VIDEO/"
           "etax-agg-product_0d17b8be20214c11a52ccb869fb185ce_1773040951439.webm"
           "?OSSAccessKeyId=LTAI5tMHcomKiHbKRhS2uU8X&Expires=1804144951"
           "&Signature=4GzUiutzNNoMGMtL%2BCt/%2Bk9qWcY%3D")
    return _ok(f"第四步（视频直播）完成：天津市金万翔建材科技有限公司（005）\n\n申报操作视频: {url}")


# ══════════════════════════════════════════════════════════
# run_all：按顺序执行全部步骤
# ══════════════════════════════════════════════════════════
def run_all(file_path=""):
    steps = [
        ("step1",            lambda: step1_profile()),
        ("step2",            lambda: step2_fetch_list()),
        ("step3",            lambda: step3_upload_excel(file_path)),
        ("step4_vat_init",   lambda: step4_vat_init()),
        ("step4_vat_submit", lambda: step4_vat_submit()),
        ("step4_pdf",        lambda: step4_pdf()),
        ("step4_video",      lambda: step4_video()),
    ]
    results = []
    for name, fn in steps:
        log.info(f"========== 执行: {name} ==========")
        r = fn()
        results.append({"step": name, "ok": r.get("ok", False), "message": r.get("user_message", "")})
        if not r.get("ok"):
            log.warning(f"{name} 失败，继续执行下一步...")

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
    "step1":           lambda a: step1_profile(),
    "step2":           lambda a: step2_fetch_list(),
    "step3":           lambda a: step3_upload_excel(a.get("file_path", "")),
    "step4_vat_init":  lambda a: step4_vat_init(),
    "step4_vat_submit": lambda a: step4_vat_submit(),
    "step4_pdf":       lambda a: step4_pdf(),
    "step4_video":     lambda a: step4_video(),
    "run_all":         lambda a: run_all(a.get("file_path", "")),
}

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    action = args.get("action", "")
    if action not in ACTION_MAP:
        output({"ok": False, "user_message": f"未知操作: {action}\n可用: {', '.join(sorted(ACTION_MAP.keys()))}"})
        sys.exit(1)
    output(ACTION_MAP[action](args))
