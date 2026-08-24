#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archery-cli PAT 桥接 —— archery-cli skill 的 Personal Access Token (PAT) 认证
=====================================================
archery-cli 二进制本身只支持 用户名/密码 认证（session/JWT），不支持 PAT。
本脚本是该 skill 附带的 PAT 桥接，采用与 archery-sql skill 相同的认证方式：
通过 `Authorization: Bearer arp_pat_...` 调用 Archery REST API（/api/v1/*）。

PAT 解析（优先级从高到低）：
  1. --pat 命令行参数（会话级，凭证不落盘）
  2. 环境变量 ARCHERY_CLI_PAT
  3. 环境变量 ARCHERY_PAT（与 archery-sql 共用）
  4. 项目配置 .archery.json（当前目录向上查找；pat 或 accounts）
  5. 用户配置 ~/.archery.json（accounts 账号表）

Base URL 解析：
  --url > 环境变量 ARCHERY_CLI_URL > 环境变量 ARCHERY_URL > 默认 https://archery.cn-pgcloud.com

用法：
  python archery_pat.py <action> [options]

动作：
  whoami             验证令牌，返回当前用户
  instances          数据库实例列表
  instance-resource  枚举 库/表/列（--resource-type database|table|column）
  query              只读 SQL 查询（含脱敏）
  sql-check          SQL 预检（提交前自动审核）
  workflow-list      工单列表（按状态/实例/资源组/日期/关键词筛选）
  workflow-detail    工单详情（SQL 内容/审核结果/执行结果）
  workflow-log       工单日志
  workflow-rollback  工单回滚 SQL
  workflow-cancel    终止未执行的工单（等待审核/审核通过未执行/定时）
  audit-list         待我审核的工单
  workflow-submit    提交 SQL 上线工单（DDL/DML，经 REST）

依赖：
  pip install requests
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests", file=sys.stderr)
    sys.exit(1)

DEFAULT_BASE_URL = "https://archery.cn-pgcloud.com"

# 默认超时（实例全量列表等接口较慢，给足时间）
DEFAULT_TIMEOUT = 60
QUICK_TIMEOUT = 15

NO_PAT_HINT = (
    "未找到 PAT。请通过以下任一方式提供：\n"
    "  1. 命令行参数: --pat arp_pat_...\n"
    "  2. 环境变量:   ARCHERY_PAT=arp_pat_...（或 ARCHERY_CLI_PAT）\n"
    "  3. 配置文件:   项目根目录 .archery.json 或 ~/.archery.json（accounts 账号表）\n"
    "获取 PAT: 登录 Archery → 右上角头像 → Personal Access Tokens（/user/tokens/）→ 创建\n"
    "          （格式 arp_pat_...，仅显示一次）"
)


# ------------------------------------------------------------
# PAT / 配置解析（与 archery-sql 相同的多账号约定）
# ------------------------------------------------------------
def find_project_config() -> dict:
    """从当前目录向上查找 .archery.json 项目配置"""
    cur = Path.cwd()
    for d in [cur] + list(cur.parents):
        cfg = d / ".archery.json"
        if cfg.exists():
            try:
                # utf-8-sig 容忍 BOM（Windows 记事本保存）
                data = json.loads(cfg.read_text(encoding="utf-8-sig"))
                data["_path"] = str(cfg)
                return data
            except Exception:
                pass
    return {}


def load_user_config() -> dict:
    """读取用户级 ~/.archery.json（可选）"""
    cfg = Path.home() / ".archery.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {}


def resolve_pat(cli_pat: str = None, account: str = None) -> tuple:
    """按优先级解析 PAT，返回 (pat, 来源说明)"""
    # 1. 命令行参数
    if cli_pat:
        return cli_pat.strip(), "命令行 --pat"
    # 2/3. 环境变量（ARCHERY_CLI_PAT 优先，其次与 archery-sql 共用的 ARCHERY_PAT）
    for env_name in ("ARCHERY_CLI_PAT", "ARCHERY_PAT"):
        env = os.environ.get(env_name, "").strip()
        if env:
            return env, f"环境变量 {env_name}"
    # 4. 项目配置 .archery.json
    proj = find_project_config()
    if proj:
        accounts = proj.get("accounts") or {}
        if accounts:
            default = proj.get("default_account")
            name = account or default or next(iter(accounts))
            if name in accounts and accounts[name].get("pat"):
                return str(accounts[name]["pat"]).strip(), f"项目配置账号 {name} ({proj.get('_path')})"
        if proj.get("pat"):
            return str(proj["pat"]).strip(), f"项目配置 {proj.get('_path')}"
    # 5. 用户配置 ~/.archery.json
    user = load_user_config()
    accounts = user.get("accounts") or {}
    if accounts:
        default = user.get("default_account")
        name = account or default or next(iter(accounts))
        if name in accounts and accounts[name].get("pat"):
            return str(accounts[name]["pat"]).strip(), f"用户配置账号 {name}"
    raise SystemExit(NO_PAT_HINT)


def resolve_base_url(cli_url: str = None) -> str:
    url = (cli_url
           or os.environ.get("ARCHERY_CLI_URL")
           or os.environ.get("ARCHERY_URL")
           or DEFAULT_BASE_URL)
    return url.strip().rstrip("/")


class ArcheryAPI:
    def __init__(self, pat: str = None, account: str = None,
                 base_url: str = None, verify_ssl: bool = True):
        self.pat, self.pat_source = resolve_pat(pat, account)
        self.base_url = resolve_base_url(base_url)
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Authorization": f"Bearer {self.pat}",
            "Content-Type": "application/json",
            "User-Agent": "archery-cli-pat-bridge/1.0",
        })
        self._inst_cache = None

    # --------------------------------------------------------
    # 底层请求
    # --------------------------------------------------------
    def _req(self, method: str, path: str, params: dict = None,
             json_body: dict = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
        """REST 请求，统一返回 JSON；网络/超时/非 2xx 都归一为 _error 结构"""
        try:
            r = self.session.request(method, self.base_url + path, params=params,
                                     json=json_body, timeout=timeout)
        except requests.exceptions.Timeout:
            return {"_error": True, "status": -1, "msg": f"请求超时(>{timeout}s): {path}"}
        except Exception as e:
            return {"_error": True, "status": -1, "msg": f"请求失败: {e}"}

        ct = r.headers.get("Content-Type", "")
        try:
            if "json" in ct:
                body = r.json()
            else:
                body = {"_html": r.text[:300]}
        except Exception:
            body = {"_unparsed": r.text[:300]}

        if r.status_code >= 400:
            detail = body if isinstance(body, dict) else {"detail": str(body)}
            detail["_error"] = True
            detail["status_code"] = r.status_code
            if r.status_code in (401, 403):
                detail["_hint"] = "PAT 无效或权限不足；请到 头像 → Personal Access Tokens 重新创建"
            return detail
        return body

    def _get(self, path: str, params: dict = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
        return self._req("GET", path, params=params, timeout=timeout)

    def _post(self, path: str, data: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
        return self._req("POST", path, json_body=data, timeout=timeout)

    # --------------------------------------------------------
    # 认证 / 身份
    # --------------------------------------------------------
    def whoami(self) -> dict:
        """返回 PAT 对应的当前用户（令牌有效性验证）"""
        return self._get("/api/v1/user/current/", timeout=QUICK_TIMEOUT)

    # --------------------------------------------------------
    # 实例与资源
    # --------------------------------------------------------
    def instances(self, size: int = 100) -> dict:
        """实例列表（REST 的 size 上限约 500）"""
        return self._get("/api/v1/instance/", {"size": size}, timeout=DEFAULT_TIMEOUT)

    def instance_resource(self, instance_name: str = None, instance_id: int = None,
                          resource_type: str = "database", db_name: str = None,
                          tb_name: str = None, schema_name: str = None) -> dict:
        """枚举实例资源：database | schema | table | column
        可传 instance_id，或 instance_name（自动解析为 ID）
        返回 {count, result: [...]}
        """
        if not instance_id and instance_name:
            instance_id = self._find_instance_id(instance_name)
        data = {
            "instance_id": instance_id or 0,
            "resource_type": resource_type,
        }
        if db_name:
            data["db_name"] = db_name
        if tb_name:
            data["tb_name"] = tb_name
        if schema_name:
            data["schema_name"] = schema_name
        return self._post("/api/v1/instance/resource/", data, timeout=QUICK_TIMEOUT)

    def _find_instance_id(self, instance_name: str):
        """按名称解析实例 ID（拉取实例列表建缓存）"""
        if self._inst_cache is None:
            try:
                data = self.instances(size=500)
                results = data.get("results", [])
                self._inst_cache = {r.get("instance_name"): r.get("id") for r in results}
            except Exception:
                self._inst_cache = {}
        return self._inst_cache.get(instance_name)

    # --------------------------------------------------------
    # SQL 查询 / 预检
    # --------------------------------------------------------
    def query(self, instance_name: str, db_name: str, sql_content: str,
              limit_num: int = 100) -> dict:
        """只读 SQL 查询（含脱敏），POST /api/v1/query/"""
        return self._post("/api/v1/query/", {
            "instance_name": instance_name,
            "db_name": db_name,
            "sql_content": sql_content,
            "limit_num": limit_num,
        }, timeout=DEFAULT_TIMEOUT)

    def sql_check(self, instance_id: int = None, instance_name: str = None,
                  db_name: str = None, full_sql: str = "") -> dict:
        """SQL 预检，POST /api/v1/workflow/sqlcheck/"""
        if not instance_id and instance_name:
            instance_id = self._find_instance_id(instance_name)
        return self._post("/api/v1/workflow/sqlcheck/", {
            "instance_id": instance_id or 0,
            "db_name": db_name,
            "full_sql": full_sql,
        }, timeout=DEFAULT_TIMEOUT)

    # --------------------------------------------------------
    # 工单
    # --------------------------------------------------------
    def workflow_list(self, status: str = "", search: str = "",
                      engineer: str = "", group_name: str = "", db_name: str = "",
                      instance_id: int = None, start_time: str = "",
                      end_time: str = "", page: int = 1, page_size: int = 10) -> dict:
        """工单列表（全部筛选条件可选；不传 status 则不过滤状态）"""
        params = {"page": page, "size": page_size}
        if status:
            params["workflow__status"] = status
        if search:
            params["workflow__workflow_name__icontains"] = search
        if engineer:
            params["workflow__engineer"] = engineer
        if group_name:
            params["workflow__group_name"] = group_name
        if db_name:
            params["workflow__db_name"] = db_name
        if instance_id:
            params["workflow__instance_id"] = instance_id
        if start_time:
            params["workflow__create_time__gte"] = start_time
        if end_time:
            params["workflow__create_time__lt"] = end_time
        return self._get("/api/v1/workflow/", params, timeout=DEFAULT_TIMEOUT)

    def workflow_detail(self, workflow_id: int) -> dict:
        """工单详情（含 SQL 内容/审核结果/执行结果）"""
        return self._get(f"/api/v1/workflow/{workflow_id}", timeout=QUICK_TIMEOUT)

    def workflow_log(self, workflow_id: int, workflow_type: int = 2,
                     page: int = 1, page_size: int = 20) -> dict:
        """工单日志"""
        return self._post("/api/v1/workflow/log/", {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "page": page,
            "page_size": page_size,
        }, timeout=QUICK_TIMEOUT)

    def workflow_rollback(self, workflow_id: int) -> dict:
        """回滚 SQL（已执行工单的回滚语句）"""
        return self._post("/api/v1/workflow/rollback/", {
            "workflow_id": workflow_id,
        }, timeout=QUICK_TIMEOUT)

    def workflow_cancel(self, workflow_id: int, workflow_type: int = 2,
                        engineer: str = None, remark: str = "agent 终止") -> dict:
        """终止工单：仅限 waiting/review_pass/timingtask 等未执行状态
        engineer 缺省时用 PAT 对应账号
        """
        if not engineer:
            me = self.whoami()
            engineer = me.get("username") or ""
        return self._post("/api/v1/workflow/audit/", {
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "audit_type": "cancel",
            "engineer": engineer,
            "audit_remark": remark,
        }, timeout=QUICK_TIMEOUT)

    def audit_list(self, engineer: str = None, workflow_type: int = 2,
                   page: int = 1, page_size: int = 20) -> dict:
        """待我审核的工单列表"""
        if not engineer:
            me = self.whoami()
            engineer = me.get("username") or ""
        return self._post("/api/v1/workflow/auditlist/", {
            "engineer": engineer,
            "workflow_type": workflow_type,
            "page": page,
            "page_size": page_size,
        }, timeout=QUICK_TIMEOUT)

    def workflow_submit(self, content: dict) -> dict:
        """提交 SQL 上线工单：POST /api/v1/workflow/（WorkflowContent 结构）"""
        return self._post("/api/v1/workflow/", content, timeout=DEFAULT_TIMEOUT)


def build_submit_payload(api: ArcheryAPI, args) -> dict:
    """从命令行参数构造 WorkflowContent（也可用 --payload/--payload-file 直接传完整 JSON）"""
    if args.payload_file:
        return json.loads(Path(args.payload_file).read_text(encoding="utf-8-sig"))
    if args.payload:
        return json.loads(args.payload)

    sql_content = args.sql
    if not sql_content and args.sql_file:
        sql_content = Path(args.sql_file).read_text(encoding="utf-8-sig")
    if not sql_content or not args.db:
        raise SystemExit("workflow-submit 需要 --payload/--payload-file，"
                         "或 (--sql 或 --sql-file) + --db")

    instance_id = args.instance_id
    if not instance_id and args.instance:
        instance_id = api._find_instance_id(args.instance)
    if not instance_id:
        raise SystemExit(f"无法解析实例：请传 --instance-id，或确认 --instance 名称存在（当前: {args.instance!r}）")

    engineer = args.engineer
    if not engineer:
        me = api.whoami()
        engineer = me.get("username") or ""

    workflow = {
        "workflow_name": args.name or "archery-cli PAT 提交",
        "db_name": args.db,
        "instance": instance_id,
        "engineer": engineer,
        "syntax_type": args.syntax_type,
        "is_backup": not args.no_backup,
    }
    if args.group_id:
        workflow["group_id"] = args.group_id
    if args.group:
        workflow["group_name"] = args.group
    if args.component_name:
        workflow["component_name"] = args.component_name
    if args.demand_url:
        workflow["demand_url"] = args.demand_url
    return {
        "workflow": workflow,
        "workflow_id": 0,
        "sql_content": sql_content,
        "review_content": "",
        "execute_result": "",
    }


def main():
    # Windows 控制台默认 GBK，统一 UTF-8 输出避免中文/结果乱码报错
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(
        description="archery-cli PAT 桥接：用 PAT 调用 Archery REST API（与 archery-sql 同认证方式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("action", choices=[
        "whoami", "instances", "instance-resource", "query", "sql-check",
        "workflow-list", "workflow-detail", "workflow-log", "workflow-rollback",
        "workflow-cancel", "audit-list", "workflow-submit",
    ], help="要执行的操作")
    # 认证 / 连接
    parser.add_argument("--pat", default=None, help="Personal Access Token（优先于环境变量）")
    parser.add_argument("--account", default=None, help="配置文件 accounts 中的账号名")
    parser.add_argument("--url", default=None, help=f"Archery 地址（默认取环境变量或 {DEFAULT_BASE_URL}）")
    parser.add_argument("--insecure", action="store_true", help="跳过 SSL 证书校验")
    # 实例 / 资源
    parser.add_argument("--instance", default="", help="实例名称")
    parser.add_argument("--instance-id", type=int, help="实例 ID（优先于名称）")
    parser.add_argument("--size", type=int, default=100, help="instances 列表条数（上限约 500）")
    parser.add_argument("--resource-type", choices=["database", "schema", "table", "column"],
                        default="database")
    parser.add_argument("--db", default="", help="数据库名")
    parser.add_argument("--tb", default="", help="表名")
    parser.add_argument("--schema", default="", help="schema 名")
    # SQL
    parser.add_argument("--sql", default="", help="SQL 内容")
    parser.add_argument("--sql-file", default="", help="从文件读取 SQL")
    parser.add_argument("--limit-num", type=int, default=100, help="查询行数上限")
    # 工单
    parser.add_argument("--id", type=int, help="工单 ID")
    parser.add_argument("--workflow-type", type=int, default=2, help="工单类型 1=查询工单 2=SQL上线 3=清理工单")
    parser.add_argument("--status", default="", help="工单状态过滤，如 workflow_finish / workflow_manreviewing")
    parser.add_argument("--search", default="", help="工单名关键词")
    parser.add_argument("--engineer", default="", help="提交人/经办人")
    parser.add_argument("--group", default="", help="资源组名")
    parser.add_argument("--group-id", type=int, help="资源组 ID")
    parser.add_argument("--start-time", default="", help="创建时间起 (2026-08-01T00:00:00)")
    parser.add_argument("--end-time", default="", help="创建时间止")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--remark", default="agent 终止", help="终止工单备注")
    # 提交工单
    parser.add_argument("--name", default="", help="工单名称（workflow_name）")
    parser.add_argument("--component-name", default="", help="微服务/组件名")
    parser.add_argument("--syntax-type", type=int, default=2, choices=[1, 2], help="1=DDL 2=DML")
    parser.add_argument("--no-backup", action="store_true", help="不备份（is_backup=false）")
    parser.add_argument("--demand-url", default="", help="需求链接（如 Jira URL）")
    parser.add_argument("--payload", default="", help="完整 WorkflowContent JSON 字符串")
    parser.add_argument("--payload-file", default="", help="完整 WorkflowContent JSON 文件")

    args = parser.parse_args()
    api = ArcheryAPI(pat=args.pat, account=args.account,
                     base_url=args.url, verify_ssl=not args.insecure)
    print(f"[认证] 使用 {api.pat_source} -> {api.base_url}", file=sys.stderr)

    def _check(data):
        """REST 层错误统一退出"""
        if isinstance(data, dict) and data.get("_error"):
            print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        return data

    try:
        result = None
        if args.action == "whoami":
            result = _check(api.whoami())
        elif args.action == "instances":
            result = _check(api.instances(size=args.size))
        elif args.action == "instance-resource":
            result = _check(api.instance_resource(
                instance_name=args.instance or None, instance_id=args.instance_id,
                resource_type=args.resource_type, db_name=args.db,
                tb_name=args.tb, schema_name=args.schema,
            ))
        elif args.action == "query":
            sql_content = args.sql or (Path(args.sql_file).read_text(encoding="utf-8-sig")
                                       if args.sql_file else "")
            if not sql_content or not args.instance or not args.db:
                raise SystemExit("query 需要 --instance --db 和 (--sql 或 --sql-file)")
            result = _check(api.query(args.instance, args.db, sql_content, args.limit_num))
        elif args.action == "sql-check":
            sql_content = args.sql or (Path(args.sql_file).read_text(encoding="utf-8-sig")
                                       if args.sql_file else "")
            result = _check(api.sql_check(
                instance_id=args.instance_id, instance_name=args.instance or None,
                db_name=args.db, full_sql=sql_content,
            ))
        elif args.action == "workflow-list":
            result = _check(api.workflow_list(
                status=args.status, search=args.search, engineer=args.engineer,
                group_name=args.group, db_name=args.db,
                instance_id=args.instance_id,
                start_time=args.start_time, end_time=args.end_time,
                page=args.page, page_size=args.page_size,
            ))
        elif args.action == "workflow-detail":
            result = _check(api.workflow_detail(args.id))
        elif args.action == "workflow-log":
            result = _check(api.workflow_log(args.id, args.workflow_type, args.page, args.page_size))
        elif args.action == "workflow-rollback":
            result = _check(api.workflow_rollback(args.id))
        elif args.action == "workflow-cancel":
            result = _check(api.workflow_cancel(args.id, args.workflow_type, args.engineer or None, args.remark))
        elif args.action == "audit-list":
            result = _check(api.audit_list(args.engineer or None, args.workflow_type,
                                           args.page, args.page_size))
        elif args.action == "workflow-submit":
            payload = build_submit_payload(api, args)
            result = _check(api.workflow_submit(payload))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except SystemExit:
        raise
    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
