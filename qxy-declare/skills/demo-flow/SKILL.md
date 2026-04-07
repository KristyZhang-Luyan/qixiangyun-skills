---
name: demo-flow
description: |
  五步演示流程。当用户说"申报/报税"但没有指定具体企业时激活。
  触发词：申报、报税、演示、跑流程、全流程、开始报税（不指定企业）。
  不触发：明确指定了某一家企业做某个操作。
---

# 五步演示流程

用户提到申报/报税但**没有指定具体企业**，或明确说"演示/跑流程"。按5步顺序执行 demo_flow.py。

## 你是翻译器

**你发给用户的消息 = python3 返回 JSON 中 `user_message` 字段的值。**

**当 user_message 包含链接时必须完整原样发送，不能省略。**

**禁止流程播报：不要说"第X步"，直接说在做什么（如"正在获取清册"）。**

## 执行步骤

### 第1步：企业画像

```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step1"}'
```

把返回的画像摘要发给用户。**继续第2步（不等用户）。**

### 第2步：获取清册（7家企业）

```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step2"}'
```

把清册汇总发给用户。**继续第3步阶段1（不等用户）。**

### 第3步：财务报表上传

**阶段1：提示上传**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step3"}'
```

把返回的 user_message 发给用户。**停下来等用户上传 Excel 文件。**

**阶段2：用户上传文件后**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step3","file_path":"用户上传的文件路径"}'
```

把"已成功申报"消息发给用户。**继续第4步。**

### 第4步：企业所得税

```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step4"}'
```

把申报结果发给用户。**继续第5步子步骤5a。**

### 第5步：增值税全流程（4个子步骤）

**5a. 批量初始化**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step5_vat_init"}'
```

返回的 user_message 包含 markdown 表格，**必须原样发送，不要改写格式。停下来等用户确认。**

**5b. 用户确认后 → 批量申报提交**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step5_vat_submit"}'
```

**5c. PDF 下载**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step5_pdf"}'
```

**返回的 user_message 中的链接必须原样展示，不能省略。**

**5d. 视频直播**
```bash
python3 {{skill_dir}}/scripts/demo_flow.py '{"action":"step5_video"}'
```

**返回的视频链接必须原样展示。**

## 用户交互节点（必须停下来等用户）

| 位置 | 等什么 |
|------|--------|
| 第3步阶段1后 | 等用户上传 Excel 文件 |
| 第5步 5a 后 | 等用户确认增值税初始化数据 |

其他步骤之间不需要等用户，可以连续执行。

## 绝对禁止

- 禁止省略链接（URL），用户需要点击
- 禁止改写 markdown 表格格式
- 禁止流程播报（"第X步"）
- 禁止在回复中暴露 JSON 或技术信息
