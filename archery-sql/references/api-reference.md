# Archery API 参考

> 基址：`https://archery.cn-pgcloud.com`
> 认证：**PAT（Personal Access Token）** — `Authorization: Bearer arp_pat_xxx`
> 全部走 REST API（`/api/v1/*`），OpenAPI 文档在 `GET /api/schema/?format=json`

## 一、REST API（PAT 认证，Skill 使用）

### 认证
| 接口 | 方法 | 说明 |
|---|---|---|
| `GET /api/v1/user/current/` | GET | 当前 PAT 对应用户（验证认证有效性） |
| `GET /api/v1/tokens/` | GET | PAT 列表 |
| `POST /api/v1/tokens/` | POST | 创建 PAT（需网页端配置） |

### 工单类
| 接口 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `GET /api/v1/workflow/` | GET | workflow__status, workflow__workflow_name__icontains, workflow__engineer, workflow__group_name, workflow__db_name, workflow__instance_id, workflow__create_time__gte/__lt, page, size | 工单列表（建议必带筛选，否则全量慢） |
| `GET /api/v1/workflow/{id}` | GET | — | 工单详情（含 workflow 元数据） |
| `POST /api/v1/workflow/log/` | POST | workflow_id, workflow_type=2, page, page_size | 工单日志 |
| `POST /api/v1/workflow/rollback/` | POST | workflow_id | 回滚 SQL |
| `POST /api/v1/workflow/auditlist/` | POST | engineer, workflow_type, page, page_size | 待审核清单 |
| `POST /api/v1/workflow/audit/` | POST | workflow_id, workflow_type=2, audit_type [pass/cancel], engineer, audit_remark | **审核/终止工单**（cancel=终止） |
| `POST /api/v1/workflow/sqlcheck/` | POST | instance_id, db_name, full_sql | SQL 预检 |
| `POST /api/v1/workflow/` | POST | WorkflowContent | 提交工单 |

### 查询类
| 接口 | 方法 | 参数 | 说明 |
|---|---|---|---|
| `GET /api/v1/instance/` | GET | size（单页最多 500） | 实例列表（全量 451 条） |
| `POST /api/v1/instance/resource/` | POST | instance_id, resource_type[database/schema/table/column], db_name, tb_name | 实例资源树（返回 {count, result}） |
| `POST /api/v1/query/` | POST | instance_name, db_name, sql_content, limit_num | 执行只读 SQL（含脱敏） |

### 提交工单（WorkflowContent 结构）
```json
{
  "workflow": {
    "workflow_name": "工单名称",
    "workflow_title": "工单名称",
    "group_id": 32,
    "group_name": "e-erp",
    "component_name": "eerp-biz-sales",
    "db_name": "eerp_sales",
    "syntax_type": 2,
    "is_backup": true,
    "demand_url": "https://jira.xxx/browse/PSDK-12345",
    "engineer": "jian.bj",
    "instance": 216
  },
  "workflow_id": 0,
  "sql_content": "UPDATE xxx SET y=1 WHERE id=1;",
  "review_content": "",
  "execute_result": ""
}
```

## 二、页面接口（Session Cookie 方式，仅供兜底参考）

> 页面接口需 Session Cookie + `X-CSRFToken` + `X-Requested-With: XMLHttpRequest`
> Skill 已不再使用此方式（改用 PAT + REST），但保留参考。

- `POST /sqlworkflow_list/` 工单列表（页面版）
- `GET /sqlworkflow/detail_content/?workflow_id=` 工单详情（页面版）
- `POST /query/` 执行查询（页面版）
- `POST /simplecheck/` SQL 预检（页面版）
- `POST /autoreview/` 定制版提交工单（HTML form，非 JSON）

## 三、数据字典

### 工单状态
| 值 | 含义 | 可终止 |
|---|---|---|
| workflow_finish | 已正常结束 | ❌ |
| workflow_abort | 人工终止流程 | ❌ |
| workflow_manreviewing | 等待审核人审核 | ✅ |
| workflow_review_pass | 审核通过 | ✅ |
| workflow_timingtask | 定时执行 | ✅ |
| workflow_queuing | 排队中 | ✅ |
| workflow_executing | 执行中 | ❌ |
| workflow_autoreviewwrong | 自动审核不通过 | ❌ |
| workflow_exception | 执行有异常 | ❌ |

### SQL 类型（syntax_type）
| 值 | 含义 |
|---|---|
| 1 | DDL |
| 2 | DML |

### 实例环境
| 值 | 含义 |
|---|---|
| qa | 测试环境 |
| prod | 生产环境 |

### 资源组
`e-erp`、`e-wms-cloud`、`pd-platform`、`e-wms-v611`

### 简单检查 errlevel
| 值 | 含义 |
|---|---|
| 0 | 通过 |
| 1 | 警告 |
| 2 | 错误（提交会被拒绝） |

## 四、工单详情行字段
| 字段 | 说明 |
|---|---|
| id | 序号 |
| stage | CHECKED / EXECUTED |
| errlevel | 0/1/2 |
| stagestatus | 状态描述（如 "Audit Completed" / "Execute Successfully"） |
| errormessage | 错误信息 |
| sql | 单条 SQL |
| affected_rows | 影响行数 |
| backup_dbname | 备份库名 |
| execute_time | 执行耗时 |
| sequence | 执行序号 |