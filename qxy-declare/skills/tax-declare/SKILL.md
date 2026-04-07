---
name: tax-declare
description: |
  单企业纳税申报。当用户明确只针对 1 家企业做 1 个操作时激活。
  触发词：给XX报税、XX申报增值税、查XX的清册、帮XX报税。
  不触发：用户没指定企业、多家企业、批量、演示。
---

# 单企业纳税申报

用户明确指定了 **1 家企业** 做 **1 个操作**（如"给金万翔报增值税"、"查 001 的清册"）。

## 你是翻译器

**你发给用户的消息 = python3 返回 JSON 中 `user_message` 字段的值。禁止发 JSON、task_id、状态名等任何技术信息。**

当 `user_message` 包含链接（URL）时，必须完整原样发送，不能省略。

## 企业名称 → ID 查找

当用户只说企业名或简称时，从 `company_mapping.md` 查出 `company_id`、`agg_org_id`、`company_name`，不要反问用户要 ID。

## 状态机交互流程

### 第1轮：创建任务

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"create","company_id":"从mapping查出","company_name":"企业全称","agg_org_id":"从mapping查出","period":"2026-03"}'
```

返回 `user_message` 发给用户。**记住返回的 `task_id`。**

### 第2轮起：用户回复后 inject + advance

根据 `waiting_for` 字段：

| waiting_for | 用户说了什么 | inject data_key |
|---|---|---|
| notify_taxes_ack | "好的，开始申报" | notify_taxes_ack |
| uploaded_excel | 用户上传了文件 | uploaded_excel |
| income_reply | "没有/有无票收入" | income_reply |
| tax_confirm_ack | "确认，提交吧" | tax_confirm_ack |
| complete_ack | "收到了" | complete_ack |

**每次执行两条命令：**

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"inject","task_id":"记住的task_id","data_key":"上面的key","data_value":{"user_said":"用户的真实原话"}}'
```

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"advance","task_id":"记住的task_id"}'
```

取 advance 返回的 `user_message` 发给用户。

### 错误处理

- `ok: false` → 用简单的话告知用户原因
- `waiting_for` 变化 → 按新 waiting_for 对应的 key 注入
- 申报完成后有 `summary.total_payable > 0` → 询问用户是否缴款

## 缴款衔接

申报完成后如果 `total_payable > 0`：

```bash
python3 {{skill_dir}}/scripts/state_machine.py '{"action":"create","company_id":"沿用申报值","company_name":"沿用","agg_org_id":"沿用","period":"沿用","declare_result":{"total_payable":从summary取值,"tax_details":从summary取值}}'
```

后续同样 inject + advance，直到缴费完成。

## 绝对禁止

- 禁止自己编造 user_said
- 禁止跳过任何 blocked 状态
- 禁止在回复中暴露 JSON 或技术信息
- 禁止流程播报（"第X步"），直接说在做什么
