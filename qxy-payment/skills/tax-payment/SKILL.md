---
name: tax-payment
description: |
  税款缴纳（三方协议扣款）。当用户提到缴款/缴费/缴税/扣款时激活。
  触发词：缴款、缴费、缴税、扣款、完税证明。
  不触发：申报（那是 tax-declare）。
---

# 税款缴纳

用户要给企业缴纳已申报的税款。缴款使用三方协议直接银行扣款。

## 你是翻译器

**你发给用户的消息 = python3 返回 JSON 中 `user_message` 字段的值。禁止发 JSON、task_id、状态名。**

## 前提条件

缴款前必须有已完成的申报任务。如果用户直接说"缴款"而未经过申报流程：
1. 确认企业和期间
2. 让用户确认缴款金额

## 状态机交互流程

### 第1轮：创建缴款任务

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"create","company_id":"xxx","company_name":"公司名","agg_org_id":"12345","period":"2026-03","declare_result":{"total_payable":1500.00,"tax_details":[{"tax_name":"增值税","final_amount":1500.00}]}}'
```

- `declare_result` 中的金额必须来自申报结果，禁止编造
- 返回 `user_message` 发给用户，**记住 `task_id`**

### 第2轮起：inject + advance

| waiting_for | 用户说了什么 | inject data_key |
|---|---|---|
| payment_confirm | "确认缴款" | payment_confirm |
| complete_ack | "收到了" | complete_ack |

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"inject","task_id":"记住的task_id","data_key":"payment_confirm","data_value":{"user_said":"用户原话"}}'
```

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"advance","task_id":"记住的task_id"}'
```

### 状态流转

```
INIT → CONFIRM_PAYMENT（等用户确认）→ EXECUTE_PAY → CHECK_RESULT → DOWNLOAD_CERT → NOTIFY_COMPLETE（等用户确认）→ DONE
```

- `EXECUTE_PAY → CHECK_RESULT → DOWNLOAD_CERT` 涉及 API 轮询，耗时较长
- 缴款失败不影响已完成的申报

## 绝对禁止

- 禁止自己编造 user_said 或代替用户确认缴款
- 禁止编造金额——金额必须来自申报结果
- 禁止在用户未确认时执行缴款
- 禁止在回复中暴露 JSON 或技术信息
