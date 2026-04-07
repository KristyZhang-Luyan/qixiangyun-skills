---
name: batch-declare
description: |
  多企业批量纳税申报。当用户提到多家企业或"全部/所有/批量"申报时激活。
  触发词：所有企业申报、批量报税、给001-005报增值税、全部报税。
  不触发：只说1家企业。
---

# 批量纳税申报

用户要给 **2家及以上企业** 做同一税种的申报。

## 你是翻译器

**你发给用户的消息 = python3 返回 JSON 中 `user_message` 字段的值。禁止发 JSON、task_id、状态名。**

## 企业列表构建

从 `company_mapping.md` 查出所有涉及企业的 company_id、company_name、agg_org_id。用户只说简称也要自动匹配。

## 状态机交互流程

### 第1轮：创建批量任务

```bash
python3 {{skill_dir}}/scripts/batch_state_machine.py '{"action":"create","companies":[{"company_id":"QXY100031100000001","company_name":"北京数算科技有限公司","agg_org_id":"5208291448799296"},{"company_id":"QXY100031100000002","company_name":"北京星云智联科技有限公司","agg_org_id":"5208295720930176"}],"period":"2026-03","tax_type":"vat"}'
```

- `tax_type`: `"vat"`（增值税）或 `"cit"`（企业所得税）
- 返回 `user_message` 发给用户，**记住 `task_id`**

### 第2轮起：inject + advance

根据 `waiting_for` 字段：

| waiting_for | 用户说了什么 | inject data_key |
|---|---|---|
| batch_notify_ack | "确认，开始申报" | batch_notify_ack |
| batch_tax_confirm | "确认申报" | batch_tax_confirm |
| batch_complete_ack | "收到了" | batch_complete_ack |

```bash
python3 {{skill_dir}}/scripts/batch_state_machine.py '{"action":"inject","task_id":"记住的task_id","data_key":"上面的key","data_value":{"user_said":"用户原话"}}'
```

```bash
python3 {{skill_dir}}/scripts/batch_state_machine.py '{"action":"advance","task_id":"记住的task_id"}'
```

取 advance 返回的 `user_message` 发给用户。

### 批量操作特点

- **全部成功才继续**：任何一家失败 → 整个批量任务终止并报错
- `task_id` 以 `batch_` 开头，与单企业 `decl_` 前缀不冲突
- `BATCH_DATA_INIT` 和 `BATCH_SUBMIT` 耗时较长，advance 超时设 300-600 秒

## 绝对禁止

- 禁止自己编造 user_said
- 禁止一家一家循环调用单企业 state_machine
- 禁止在回复中暴露 JSON 或技术信息
- 禁止流程播报（"第X步"）
