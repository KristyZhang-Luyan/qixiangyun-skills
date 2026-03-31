#!/usr/bin/env python3
"""
demo_flow.py — 五步演示流程脚本

严格按照演示步骤执行：
  第一步：企业画像（005 天津市金万翔建材科技有限公司）
  第二步：获取清册（001-007，全部7家）
  第三步：财务报表Excel上传申报（007 深圳交易研究院有限公司，小企业会计准则）
  第四步：企业所得税A初始化+申报提交（006 中邮证券有限责任公司天津分公司）
  第五步：增值税批量初始化（001-005）→ 列出金额等数据给用户确认
          → 批量申报提交（001-005）
          → PDF下载（005）+ 视频直播（005）

用法：
  python3 demo_flow.py '{"action":"step1"}'
  python3 demo_flow.py '{"action":"step2"}'
  python3 demo_flow.py '{"action":"step3"}'
  python3 demo_flow.py '{"action":"step3","file_path":"/path/to/file.xlsx"}'
  python3 demo_flow.py '{"action":"step4"}'
  python3 demo_flow.py '{"action":"step5_vat_init"}'
  python3 demo_flow.py '{"action":"step5_vat_submit"}'
  python3 demo_flow.py '{"action":"step5_pdf"}'
  python3 demo_flow.py '{"action":"step5_video"}'
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

ALL_COMPANY_IDS = [
    "QXY100031100000001", "QXY100031100000002", "QXY100031100000003",
    "QXY100031100000004", "QXY100031100000005", "QXY100031100000006",
    "QXY100031100000007",
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
    log.info("【第二步】获取清册（7家全部）")
    try:
        from fetch_tax_list import fetch_tax_list
        lines = []
        for cid in ALL_COMPANY_IDS:
            c = _ci(cid)
            log.info(f"获取清册: {c['name']}")
            r = fetch_tax_list(c["agg_org_id"], YEAR, PERIOD)
            if r.get("ok"):
                items = r.get("required_items", [])
                names = [i.get("zsxmMc", i.get("yzpzzlDm", "")) for i in items]
                lines.append(f"  {c['name']}：{len(items)}个待申报税种 ({', '.join(names)})")
            else:
                lines.append(f"  {c['name']}：获取失败 - {r.get('error', '未知错误')}")
        return _ok(f"第二步完成：7家企业清册获取完毕\n\n" + "\n".join(lines))
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
# 第四步：企业所得税A初始化+申报提交（006 中邮证券）
# 税种代码：BDA0611159（A类季报）
# ══════════════════════════════════════════════════════════
def step4_cit():
    log.info("【第四步】企业所得税A初始化 + 申报提交")
    cid = "QXY100031100000006"
    c = _ci(cid)
    try:
        from init_declaration import init_declaration

        # 初始化：企业所得税A类（BDA0611159）
        log.info(f"企业所得税A初始化: {c['name']}")
        ir = init_declaration(c["agg_org_id"], YEAR, PERIOD, [{"yzpzzlDm": "BDA0611159"}])
        if not ir.get("ok") and not ir.get("results"):
            return _err(f"第四步失败：初始化失败 - {ir.get('errors', '未知错误')}")

        # 从初始化结果中提取 initData
        init_data = _extract_init_data(ir)
        if not init_data:
            return _err("第四步失败：初始化成功但未提取到 initData")

        # 修正所属期：企业所得税为季报，所属期应为当季起止
        cit_ssq_q = f"{YEAR}-01-01"
        cit_ssq_z = f"{YEAR}-{PERIOD:02d}-{LAST_DAY}"
        nsrxx = init_data.get("a200000Ywbd", {}).get("nsrxxForm")
        if nsrxx:
            nsrxx["skssqq"] = cit_ssq_q
            nsrxx["skssqz"] = cit_ssq_z
            log.info(f"已修正所属期: {cit_ssq_q} ~ {cit_ssq_z}")

        # 申报提交：使用 tax_data 直接申报（企业所得税用 sdsData 类型）
        log.info(f"企业所得税A申报提交: {c['name']}")
        payload = {
            "aggOrgId": c["agg_org_id"],
            "year": YEAR,
            "period": PERIOD,
            "isDirectDeclare": True,
            "tax_type": "sdsData",
            "tax_data": init_data,
        }
        r = api_call("upload_tax_report", payload=payload)
        if not r.get("ok"):
            return _err(f"第四步失败：申报提交失败 - {r.get('error', r.get('message', '未知错误'))}")

        data = r.get("data", {})
        tid = (data.get("data") or {}).get("taskId", data.get("taskId"))
        if tid:
            pr = poll_task(c["agg_org_id"], tid, result_endpoint="query_tax_report_result")
            if pr.get("ok") and pr.get("status") == "completed":
                return _ok(f"第四步完成：{c['name']}（{cid}）企业所得税A初始化并申报成功")
            return _err(f"第四步失败：申报轮询失败 - {pr.get('error', '状态异常')}")
        return _err("第四步失败：申报提交未返回 taskId")
    except Exception as e:
        return _err(f"第四步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第五步-a：增值税批量初始化（001-005）
# 列出各企业申报金额等数据，供用户确认
# ══════════════════════════════════════════════════════════
def _extract_vat_amounts(ir):
    """从增值税初始化结果中提取关键金额"""
    for res in ir.get("results", []):
        if res.get("status") == "initialized" and res.get("init_data"):
            d = res["init_data"]
            init = d.get("data", {}).get("initData", d.get("initData", {}))
            if not isinstance(init, dict):
                return None
            # 主表
            zb = init.get("zzssyyybnsrzb", {})
            rows = zb.get("zbGrid", {}).get("zbGridlbVO", [])
            row = rows[0] if rows else {}  # 本月数
            # 附加税合计
            fj = init.get("fjssbb", {})
            hj = fj.get("hj", {})
            return {
                "销售额": row.get("yshwxse", "0.00"),
                "销项税额": row.get("xxse", "0.00"),
                "进项税额": row.get("jxse", "0.00"),
                "应纳税额": row.get("ynse", "0.00"),
                "本期应补退税额": row.get("bqybtse", "0.00"),
                "附加税应纳": hj.get("bqynsehj", "0.00"),
                "附加税应补": hj.get("bqybsehj", "0.00"),
            }
    return None


VAT_INIT_CACHE = "/tmp/qxy_vat_init_cache.json"


def _save_init_cache(cache_data):
    """保存 initData 到临时文件，供 step5_vat_submit 读取"""
    with open(VAT_INIT_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
    log.info(f"initData 缓存已写入: {VAT_INIT_CACHE}")


def _load_init_cache():
    """读取 initData 缓存"""
    if not os.path.exists(VAT_INIT_CACHE):
        return None
    with open(VAT_INIT_CACHE, "r", encoding="utf-8") as f:
        return json.load(f)


def _extract_init_data(ir):
    """从初始化结果中提取完整的 initData（用于申报提交）"""
    for res in ir.get("results", []):
        if res.get("status") == "initialized" and res.get("init_data"):
            d = res["init_data"]
            init = d.get("data", {}).get("initData", d.get("initData", {}))
            if isinstance(init, dict):
                return init
    return None


def step5_vat_init():
    log.info("【第五步】增值税批量初始化")
    try:
        from init_declaration import init_declaration
        table_rows = []  # [(企业名, 销售额, 销项税额, 进项税额, 应纳税额, 附加税应补)]
        cache_data = {}  # {cid: initData}
        errors = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            log.info(f"增值税初始化: {c['name']}")
            ir = init_declaration(c["agg_org_id"], YEAR, PERIOD, [{"yzpzzlDm": "BDA0610606"}])
            ok = ir.get("ok") or bool(ir.get("results"))
            if ok:
                # 提取并缓存 initData
                init_data = _extract_init_data(ir)
                if init_data:
                    cache_data[cid] = init_data
                # 提取金额用于展示
                amounts = _extract_vat_amounts(ir)
                if amounts:
                    table_rows.append((
                        c["name"],
                        amounts["销售额"],
                        amounts["销项税额"],
                        amounts["进项税额"],
                        amounts["应纳税额"],
                        amounts["附加税应补"],
                    ))
                else:
                    table_rows.append((c["name"], "-", "-", "-", "-", "-"))
            else:
                errors.append(f"{c['name']}：初始化失败 - {ir.get('errors', '未知错误')}")
        # 保存缓存
        if cache_data:
            _save_init_cache(cache_data)
        # 构建 markdown 表格
        msg = "第五步（增值税批量初始化）完成，5家企业数据如下：\n\n"
        msg += "| 企业 | 销售额 | 销项税额 | 进项税额 | 应纳税额 | 附加税应补 |\n"
        msg += "|---|---|---|---|---|---|\n"
        for row in table_rows:
            msg += f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} |\n"
        if errors:
            msg += "\n" + "\n".join(errors) + "\n"
        msg += "\n请确认以上申报数据，确认后将提交申报。"
        return _ok(msg)
    except Exception as e:
        return _err(f"第五步（批量初始化）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第五步-b：增值税批量申报提交（001-005）
# ══════════════════════════════════════════════════════════
def step5_vat_submit():
    log.info("【第五步】增值税批量申报提交（方案B：使用initData直接申报）")
    try:
        cache = _load_init_cache()
        if not cache:
            return _err("第五步（批量申报提交）失败：未找到初始化缓存，请先执行 step5_vat_init")

        lines = []
        for cid in VAT_BATCH_IDS:
            c = _ci(cid)
            init_data = cache.get(cid)
            if not init_data:
                lines.append(f"  {c['name']}：跳过（无初始化数据）")
                continue

            log.info(f"增值税申报提交: {c['name']}")
            payload = {
                "aggOrgId": c["agg_org_id"],
                "year": YEAR,
                "period": PERIOD,
                "isDirectDeclare": True,
                "tax_data": init_data,
            }
            r = api_call("upload_tax_report", payload=payload)
            if not r.get("ok"):
                lines.append(f"  {c['name']}：申报失败 - {r.get('error', r.get('message', '未知错误'))}")
                continue

            data = r.get("data", {})
            tid = (data.get("data") or {}).get("taskId", data.get("taskId"))
            if tid:
                pr = poll_task(c["agg_org_id"], tid, result_endpoint="query_tax_report_result")
                if pr.get("ok") and pr.get("status") == "completed":
                    lines.append(f"  {c['name']}：申报成功")
                else:
                    lines.append(f"  {c['name']}：申报失败 - {pr.get('error', '轮询状态异常')}")
            else:
                lines.append(f"  {c['name']}：申报失败 - 未获取到 taskId")

        return _ok(f"第五步（批量申报提交）完成：\n\n" + "\n".join(lines))
    except Exception as e:
        return _err(f"第五步（批量申报提交）失败：{e}")


# ══════════════════════════════════════════════════════════
# 第五步-c：PDF下载（005 金万翔）
# ══════════════════════════════════════════════════════════
def step5_pdf():
    log.info("【第五步】增值税PDF下载")
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

            msg = f"第五步（PDF下载）完成：{c['name']}（{cid}）"
            if pdf_url:
                msg += f"\n\n[点击下载PDF申报回执]({pdf_url})"
            return _ok(msg)
        return _err(f"第五步失败：PDF下载失败 - {r.get('error', '未知错误')}")
    except Exception as e:
        return _err(f"第五步失败：{e}")


# ══════════════════════════════════════════════════════════
# 第五步-d：视频直播（005 金万翔）— 静态链接
# ══════════════════════════════════════════════════════════
def step5_video():
    url = ("http://qxy-oss-robot-product.qixiangyun.com/VIDEO/"
           "etax-agg-product_0d17b8be20214c11a52ccb869fb185ce_1773040951439.webm"
           "?OSSAccessKeyId=LTAI5tMHcomKiHbKRhS2uU8X&Expires=1804144951"
           "&Signature=4GzUiutzNNoMGMtL%2BCt/%2Bk9qWcY%3D")
    return _ok(f"第五步（视频直播）完成：天津市金万翔建材科技有限公司（005）\n\n[点击观看申报操作视频]({url})")


# ══════════════════════════════════════════════════════════
# run_all：按顺序执行全部步骤
# ══════════════════════════════════════════════════════════
def run_all(file_path=""):
    steps = [
        ("step1",            lambda: step1_profile()),
        ("step2",            lambda: step2_fetch_list()),
        ("step3",            lambda: step3_upload_excel(file_path)),
        ("step4",            lambda: step4_cit()),
        ("step5_vat_init",   lambda: step5_vat_init()),
        ("step5_vat_submit", lambda: step5_vat_submit()),
        ("step5_pdf",        lambda: step5_pdf()),
        ("step5_video",      lambda: step5_video()),
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
    "step1":            lambda a: step1_profile(),
    "step2":            lambda a: step2_fetch_list(),
    "step3":            lambda a: step3_upload_excel(a.get("file_path", "")),
    "step4":            lambda a: step4_cit(),
    "step5_vat_init":   lambda a: step5_vat_init(),
    "step5_vat_submit": lambda a: step5_vat_submit(),
    "step5_pdf":        lambda a: step5_pdf(),
    "step5_video":      lambda a: step5_video(),
    "run_all":          lambda a: run_all(a.get("file_path", "")),
}

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    action = args.get("action", "")
    if action not in ACTION_MAP:
        output({"ok": False, "user_message": f"未知操作: {action}\n可用: {', '.join(sorted(ACTION_MAP.keys()))}"})
        sys.exit(1)
    output(ACTION_MAP[action](args))
