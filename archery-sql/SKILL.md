---
name: archery-sql
description: '访问 P&G Archery SQL 审核平台 (archery.cn-pgcloud.com)。Use when: 查询 SQL 上线工单/工单详情/工单日志、提交 SQL 上线工单、终止未执行的 SQL 工单、执行 SQL 只读查询、枚举数据库实例/库/表/列、SQL 语法检查、查看待办工单、查询工单回滚 SQL。不包含审核通过、执行、回滚等人工处置操作。'
argument-hint: 'SQL 审核平台操作：如 查询工单 / 提交SQL / 终止工单 / SQL查询'
user-invocable: true
---

# Archery SQL 审核平台

访问 **P&G Archery SQL 审核平台**（https://archery.cn-pgcloud.com，v1.9.1 定制版）的能力封装。

## 能力范围

### ✅ 支持的（PAT 认证 + REST API）
1. **工单查询**：工单列表（按状态/实例/资源组/日期/关键词筛选）、工单详情（SQL 内容/审核结果/执行结果）、工单日志、工单状态、回滚 SQL
2. **待办工单**：查询待自己审核的工单列表
3. **SQL 查询**：枚举实例→库→表→列、执行只读 SQL 查询（含脱敏）
4. **SQL 检查**：提交前自动审核（sql-check）
5. **提交 SQL 上线工单**（DDL/DML）——经 REST API 提交
6. **终止工单**（未执行）——错提交的工单可取消（仅限等待审核/审核通过未执行/定时等状态）
7. **认证/账号管理**：whoami 验证令牌、多账号切换（--account）

### ❌ 不支持的（需人工在系统操作）
- 审核通过（pass）工单 —— 审批必须人工
- 执行工单、定时执行、暂停/恢复
- 数据归档工单
- 其他管理操作（用户/实例/配置管理）

> ⚠️ **重要**：提交工单后，**通过审核/执行**等流程必须由人工在系统上完成。Skill 支持创建工单、查询信息、终止（取消）未执行工单。

## 认证（PAT 方式）

使用 **Personal Access Token (PAT)** 认证（`Authorization: Bearer <token>`），多账号支持三级配置。

```bash
# 方式1：命令行 --pat（会话级，推荐）—— 凭证不落盘
python archery_api.py whoami --pat "arp_pat_xxx"

# 方式2：环境变量
set ARCHERY_PAT="arp_pat_xxx"
python archery_api.py whoami

# 方式3：项目配置文件 .archery.json（项目根目录自动识别）
#      { "accounts": { "alice": {"pat": "..."}, "bob": {"pat": "..."} }, "default_account": "alice" }
python archery_api.py whoami --account alice

# 方式4：用户级配置 ~/.archery.json（可选）
```

**获取 PAT**：登录系统 → 右上角头像 → **Personal Access Tokens**（/user/tokens/）→ 创建（格式 `arp_pat_...`，仅显示一次）。

**多账号设计**（详见 [accounts-guide.md](./references/accounts-guide.md)）：
- **项目级**：项目根目录 `.archery.json` 存 `accounts` 账号表（不同账号给不同成员/微服务）
- **会话级**：AI/脚本从会话记忆读 PAT 用 `--pat` 传（不同会话可用不同账号）
- 优先级：`--pat` > 环境变量 > 项目配置 > 用户配置

## 核心脚本

所有能力通过 [archery_api.py](./scripts/archery_api.py) 提供，依赖 `requests`。

```bash
pip install requests
```

## 操作指南

### 1. 查询 SQL 上线工单
```bash
python archery_api.py workflow-list \
  --status workflow_finish \        # 状态筛选（可省略）
  --instance "eerp-qa-new" \        # 实例筛选
  --group "e-erp" \                 # 资源组筛选
  --start-date 2026-08-01 --end-date 2026-08-19  # 日期范围
  --search "关键词" \               # 模糊搜索（工单名/发起人）
  --limit 20
```

**工单状态枚举**：
- `workflow_finish` 已正常结束
- `workflow_manreviewing` 等待审核人审核
- `workflow_review_pass` 审核通过
- `workflow_timingtask` 定时执行
- `workflow_queuing` 排队中
- `workflow_executing` 执行中
- `workflow_autoreviewwrong` 自动审核不通过
- `workflow_exception` 执行有异常
- `workflow_abort` 人工终止流程

### 2. 查询工单详情
```bash
python archery_api.py workflow-detail --id 28408     # 完整 SQL + 逐条审核/执行结果
python archery_api.py workflow-status --id 28408     # 当前状态
python archery_api.py workflow-log --id 28408        # 操作日志
python archery_api.py workflow-backup --id 28408     # 回滚 SQL（需已执行+开备份）
```

### 3. 查询待办工单
```bash
python archery_api.py audit-list --workflow-type 2    # 2=SQL上线 1=查询权限申请 0=全部
```

### 4. SQL 查询（只读）
```bash
# 枚举实例 → 库 → 表 → 列
python archery_api.py instances --page-size 50
python archery_api.py instance-resource --instance "eerp-qa-new" --resource-type database
python archery_api.py instance-resource --instance "eerp-qa-new" --resource-type table --db "eerp_sales"
python archery_api.py instance-resource --instance "eerp-qa-new" --resource-type column --db "eerp_sales" --tb "business_event_log"

# 执行查询（仅 SELECT/SHOW/DESC/EXPLAIN）
python archery_api.py query --instance "eerp-qa-new" --db "eerp_sales" --sql "select * from business_event_log limit 10"
```

**资源组速查**：`e-erp` `e-wms-cloud` `pd-platform` `e-wms-v611`
**查询注意事项**：
- `instance-resource` 只接受**实例原名**（如 `eerp-qa-new`），不接受带 `[qa]` 前缀的显示名
- 查询响应含 `column_list`（列名）与 `rows`（数据）；`is_masked` 表示是否脱敏
- 生产实例查询可能被脱敏/限制

### 5. SQL 检查（提交前必做）
```bash
python archery_api.py sql-check --instance "eerp-qa-new" --db "eerp_sales" --sql "UPDATE xxx SET y=1 WHERE id=1"
# 也可以直接传实例 ID（更快，跳过实例名解析）：
python archery_api.py sql-check --id 216 --db "eerp_sales" --sql "UPDATE xxx SET y=1 WHERE id=1"
```
返回逐条 SQL 的检测结果（`errlevel`: 0=通过 1=警告 2=错误，`stagestatus` 描述），以及 `warning_count`/`error_count`。

### 6. 提交 SQL 上线工单
```bash
# 重要：先 sql-check（预检）再提交
python archery_api.py submit \
  --name "PSDK-12345 需求描述" \
  --group "e-erp" \
  --instance "eerp-qa-new" \
  --db "eerp_sales" \
  --sql "UPDATE your_table SET status='X' WHERE id=1;" \
  --syntax-type 2 \                  # 1=DDL 2=DML
  --backup 1
```
> ⚠️ 注意：`submit` 动作需配合 REST 的 WorkflowContentSerializer 提交格式，详见 [api-reference.md](./references/api-reference.md) 提交说明。若 REST 提交参数复杂，可提示用户到 Web 端提交。

### 7. 终止工单（未执行）⭐ 新增
```bash
# 终止（取消）一条未执行的工单 —— 适用于提交错误、需求变更时
python archery_api.py workflow-cancel --id 12345 --remark "误提交，取消工单"
```
- **适用状态**：等待审核（manreviewing）、审核通过未执行（review_pass）、定时执行（timingtask）、排队中（queuing）
- **发起人/审核人**可终止
- **不可终止状态**：已结束、执行中、自动审核不通过等
- 终止后工单状态变为 `workflow_abort`（人工终止流程）

### 8. 认证与账号
```bash
python archery_api.py whoami --pat "arp_pat_xxx"          # 验证令牌/查看当前账号
python archery_api.py whoami --account alice              # 用项目配置里的账号
```

## 常用工作流示例

### 场景A：用户说"帮我查一下最近工单"
1. `workflow-list --status workflow_manreviewing` 获取待审核工单（带筛选更快）
2. 按需 `workflow-detail --id X` 查看具体内容

### 场景B：用户说"提交一个 SQL 上线"
1. `instance-resource --resource-type database` 确认库
2. `sql-check` 预检 SQL → 有 errlevel=2 提示用户修正
3. `submit` 提交（带上 CI 单号作工单名）
4. 告知用户：**已提交成功，请到系统人工审核/执行**（附工单链接 `/detail/{id}/`）

### 场景C：用户说"执行一条查询"
1. 确认实例和库（从 instances + instance-resource）
2. `query` 执行
3. 返回列名+数据行，注意脱敏标记

### 场景D：用户说"我这个 CI 单的 SQL 上了没"
1. `workflow-list --search <CI编号>` 定位工单
2. `workflow-status --id X` + `workflow-log --id X` 确认进展

### 场景E：用户说"提交错了，帮我取消这个工单"
1. `workflow-status --id X` 确认工单还在未执行状态
2. `workflow-cancel --id X --remark "误提交取消"` 终止
3. 确认返回成功 + 工单状态变为 abort

## 注意事项
1. **人工处置边界**：审核通过、执行、回滚不在能力内，提交后必须人工操作。**终止工单除外**（这是可用的写操作，用于取消错提交）。
2. **提交前必检**：任何工单提交前先 `sql-check`，错误（errlevel=2）会被系统自动拒绝。
3. **SQL 只读**：`query` 只接受只读语句；DML/DDL 请走工单流程。
4. **实例名格式**：接口参数用实例原名，不是页面显示的 `[qa] xxx` 格式。
5. **PAT 过期/失效**：遇 401/403，提示用户重新创建 PAT（右上角头像 → Personal Access Tokens）。
6. **多账号切换**：不同项目/会话用 `--account` 或 `--pat` 切换，项目级配置存项目根目录 `.archery.json`（勿提交到 git）。