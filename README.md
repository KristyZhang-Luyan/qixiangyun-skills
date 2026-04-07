# 企享云记账报税 AI Agent 系统

基于 OpenClaw 多 Agent 架构的自动化税务申报与缴款系统。

## 架构

```
用户 ←→ qxy-accounting（主控）
              ├── qxy-declare（申报执行器）
              └── qxy-payment（缴款执行器）
```

| Agent | 职责 | 交互 |
|-------|------|------|
| **qxy-accounting** | 主控 Agent，与用户对话，理解意图，调度子 Agent | 直接对话 |
| **qxy-declare** | 纳税申报执行器，通过 MCP 调用企享云 API | 后台执行 |
| **qxy-payment** | 税款缴纳执行器，处理三方协议扣款 | 后台执行 |

## 目录结构

```
qixiangyun-skills-main/
│
├── qxy-accounting/                    # 主控 Agent
│   ├── AGENTS.md                      # 业务上下文（企业映射、路由规则）
│   ├── SOUL.md                        # 行为准则
│   ├── HEARTBEAT.md                   # 心跳控制
│   ├── company_mapping.md             # 企业信息映射表
│   ├── agent/
│   │   ├── AGENT.md                   # Agent 行为指令
│   │   ├── models.json                # LLM 模型配置
│   │   └── auth-profiles.json         # 认证配置
│   └── sessions/
│
├── qxy-declare/                       # 申报执行器
│   ├── agent/
│   │   ├── AGENT.md                   # 执行器指令
│   │   ├── TOOLS.md                   # 工具定义文档
│   │   ├── models.json
│   │   ├── auth-profiles.json
│   │   └── tools/                     # 共享库（被 skills 脚本 import）
│   │       ├── shared.py              # 状态持久化、通用工具
│   │       ├── qxy_mcp_lib.py         # MCP 协议通信库
│   │       ├── login.py               # 登录管理
│   │       ├── enterprise_profile.py  # 企业画像采集
│   │       ├── fetch_tax_list.py      # 获取申报清册
│   │       ├── init_declaration.py    # 初始化申报表
│   │       ├── calculate_tax.py       # 税费计算
│   │       ├── validate_declaration.py# 申报校验
│   │       ├── submit_declaration.py  # 提交申报
│   │       ├── download_receipt.py    # 下载回执 PDF
│   │       ├── payment.py             # 缴款（申报流程内）
│   │       ├── check_submit_result.py # 查询申报结果
│   │       ├── parse_pdf.py           # PDF 结构化识别
│   │       └── query_policy_kb.py     # 优惠政策查询
│   ├── skills/                        # OpenClaw Skill 包
│   │   ├── tax-declare/               # 单企业纳税申报
│   │   │   ├── SKILL.md
│   │   │   └── scripts/state_machine.py
│   │   ├── batch-declare/             # 批量纳税申报
│   │   │   ├── SKILL.md
│   │   │   └── scripts/{batch_state_machine.py, batch.py}
│   │   └── demo-flow/                 # 五步演示流程
│   │       ├── SKILL.md
│   │       └── scripts/demo_flow.py
│   └── sessions/
│
└── qxy-payment/                       # 缴款执行器
    ├── agent/
    │   ├── AGENT.md
    │   ├── models.json
    │   ├── auth-profiles.json
    │   └── tools/                     # 共享库
    │       ├── shared.py              # 状态持久化、通用工具
    │       ├── qxy_mcp_lib.py         # MCP 协议通信库
    │       └── payment.py             # 缴款执行
    ├── skills/
    │   └── tax-payment/               # 税款缴纳（三方协议扣款）
    │       ├── SKILL.md
    │       └── scripts/state_machine.py
    └── sessions/
```

## 核心业务流程

### 纳税申报（单企业）

```
INIT → ENTERPRISE_PROFILE → FETCH_LIST → NOTIFY_TAXES（用户确认）
     → DATA_INIT → TAX_CALC → CONFIRM_TAX（用户确认）
     → SUBMIT → DOWNLOAD → NOTIFY_COMPLETE（用户确认）→ DONE
```

### 纳税申报（批量）

```
BATCH_INIT → BATCH_FETCH_LIST → BATCH_NOTIFY_TAXES（用户确认）
           → BATCH_DATA_INIT → BATCH_CONFIRM_TAX（用户确认）
           → BATCH_SUBMIT → BATCH_DOWNLOAD → BATCH_NOTIFY_COMPLETE → BATCH_DONE
```

### 税款缴纳

```
INIT → CONFIRM_PAYMENT（用户确认）→ EXECUTE_PAY → CHECK_RESULT
     → DOWNLOAD_CERT → NOTIFY_COMPLETE（用户确认）→ DONE
```

## 环境配置

每个 Agent 的 `agent/tools/` 目录下需要 `.env` 文件：

```env
QXY_CLIENT_APPKEY=你的appkey
QXY_CLIENT_SECRET=你的secret
```

全局需要设置 LLM API Key：

```bash
export ZAI_API_KEY=你的智谱API密钥
```

## 沙箱测试企业

| 税号 | 企业名称 | 用途 |
|------|---------|------|
| QXY100031100000001 | 北京数算科技有限公司 | 增值税（0申报）|
| QXY100031100000002 | 北京星云智联科技有限公司 | 增值税（0申报）|
| QXY100031100000003 | 上海瀚海商贸有限公司 | 增值税（0申报）|
| QXY100031100000004 | 深圳前海新能源发展有限公司 | 增值税（0申报）|
| QXY100031100000005 | 天津市金万翔建材科技有限公司 | 增值税（有数据申报）|
| QXY100031100000006 | 中邮证券有限责任公司天津分公司 | 企业所得税A |
| QXY100031100000007 | 深圳交易研究院有限公司 | 财务报表上传 |

## 安全设计

- **user_said 强制校验**：所有 `inject` 操作必须包含用户原话，防止 AI 自行编造数据
- **反向链路验证**：状态机每次推进前验证所有前置步骤已完成，防止跳步
- **输出隔离**：子 Agent 的技术细节（JSON、状态名、task_id）不暴露给用户
- **缴款双重确认**：涉及资金操作需用户明确确认后才能执行
