# qxy-declare 所需 Tools 定义

以下是 qxy-declare Agent 需要调用的 Tool / MCP 接口清单。
每个 Tool 对应状态机中的一个脚本节点。

---

## 1. fetch_tax_list — 获取申报清单

```yaml
name: fetch_tax_list
description: 调用税费清单接口，获取企业本月应申报的税种列表
input:
  company_id: string     # 企业ID
  period: string         # 申报期 (YYYY-MM)
output:
  tax_items:             # 税种清单
    - tax_code: string   # 税种代码
      tax_name: string   # 税种名称
      due_date: string   # 截止日期
      status: string     # pending / submitted / overdue
  has_required: boolean  # 是否有需申报税种
```

## 2. init_declaration — 初始化申报表

```yaml
name: init_declaration
description: 调用税务局初始化接口，获取申报表预填数据
input:
  company_id: string
  period: string
  tax_codes: string[]    # 需要初始化的税种代码列表
output:
  forms:
    - tax_code: string
      form_id: string
      prefilled_data: object  # 预填数据 JSON
      form_schema: object     # 表单结构定义
  success: boolean
  error_message: string?
```

## 3. calculate_tax — 税费计算

```yaml
name: calculate_tax
description: |
  根据标准化申报数据，按税法公式计算各税种应缴金额。
  纯确定性计算，不使用 LLM。
input:
  company_id: string
  period: string
  declaration_data: object   # 标准化后的申报数据
  tax_codes: string[]
output:
  results:
    - tax_code: string
      tax_name: string
      taxable_amount: number   # 应税金额
      tax_rate: number         # 税率
      tax_payable: number      # 应缴税额
      deductions: number       # 减免金额
      final_amount: number     # 实际应缴
  is_all_zero: boolean         # 是否全零申报
  summary:
    total_payable: number
```

## 4. validate_declaration — 申报表校验

```yaml
name: validate_declaration
description: |
  执行申报表逻辑校验（本地规则） + 调用税务局预校验接口。
  校验内容：勾稽关系、数值范围、必填项、跨表关联。
input:
  company_id: string
  period: string
  forms: object[]            # 填写完成的申报表数据
output:
  is_valid: boolean
  errors:
    - field: string          # 出错字段
      rule: string           # 校验规则
      message: string        # 错误描述
      severity: string       # error / warning
      source: string         # local / remote (本地校验 or 税务局返回)
  warnings: object[]
```

## 5. submit_declaration — 提交申报

```yaml
name: submit_declaration
description: 调用一键申报 / 批量申报接口
input:
  company_id: string
  period: string
  forms: object[]
  mode: string               # single / batch
output:
  submission_id: string      # 提交流水号
  status: string             # submitted / queued / failed
  error_message: string?
```

## 6. check_submit_result — 查询申报结果

```yaml
name: check_submit_result
description: 查询申报提交后的处理结果（可能需要轮询）
input:
  submission_id: string
output:
  status: string             # processing / success / rejected
  result:
    - tax_code: string
      status: string
      message: string?
  rejection_reasons: string[]?
```

## 7. download_receipt — 下载申报回执

```yaml
name: download_receipt
description: 下载申报成功后的 PDF 回执
input:
  company_id: string
  period: string
  submission_id: string
output:
  pdf_url: string            # PDF 下载地址
  pdf_data: base64?          # PDF 内容 (base64)
```

## 8. parse_pdf — PDF 结构化识别

```yaml
name: parse_pdf
description: 对申报回执 PDF 进行 OCR + 结构化识别
input:
  pdf_url: string
output:
  structured_data: object    # 结构化识别结果
  raw_text: string           # 原始文本
```

## 9. query_policy_kb — 查询优惠政策知识库

```yaml
name: query_policy_kb
description: |
  从优惠政策知识库中检索与企业可能相关的政策。
  返回候选政策列表，由 LLM 做最终匹配判断。
input:
  company_id: string
  company_type: string       # 企业类型（小规模/一般纳税人等）
  industry: string           # 行业
  tax_codes: string[]        # 本次申报的税种
  period: string
output:
  policies:
    - policy_id: string
      policy_name: string
      description: string
      conditions: string[]   # 适用条件
      benefit: string        # 优惠内容
      effective_date: string
      expiry_date: string
```

---

## Tool 注册方式

在 OpenClaw 中，这些 Tool 可以通过以下方式注册：

### 方式一：MCP Server（推荐）
将上述接口封装为 MCP Server，在 agent 配置中引用：

```jsonc
// 在 AGENT.md 同目录下创建 tools.json
{
  "mcpServers": {
    "qxy-tax-api": {
      "type": "url",
      "url": "http://localhost:3001/mcp",
      "name": "qxy-tax-api"
    }
  }
}
```

### 方式二：本地脚本
在 agentDir 下创建可执行脚本，OpenClaw 会自动注册为 Tool：

```
agents/qxy-declare/agent/
├── AGENT.md
├── tools/
│   ├── fetch_tax_list.sh
│   ├── calculate_tax.py
│   ├── validate_declaration.py
│   └── ...
```
