#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archery SQL 审核平台 API 客户端（纯 PAT 认证版）
=====================================================
通过 Personal Access Token (PAT) 认证访问 https://archery.cn-pgcloud.com 的
Archery SQL 审核平台 REST API。

能力：
  - 工单: 列表/详情/日志/状态/回滚SQL/终止(未执行)
  - SQL: 实例/库/表/列枚举、只读查询、SQL预检
  - 提交: SQL 上线工单（DDL/DML，经 REST 提交）
  - 元数据: 我的实例、组内实例/微服务/审批人

多账号支持（PAT 优先级从高到低）：
  1. --pat 命令行参数（会话级：由调用方从会话记忆传入）
  2. 环境变量 ARCHERY_PAT
  3. 项目配置文件 .archery.json（当前目录向上查找，项目级）
  4. 用户配置文件 ~/.archery.json（可选，含 accounts 账号表）
  5. 会话记忆（由调用方以 --pat 显式传入即可）

用法：
  python archery_api.py <action> [options]

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

BASE_URL = "https://archery.cn-pgcloud.com"

# 开发用默认 PAT（请用环境变量/项目配置覆盖）
DEFAULT_PAT = ""

# 默认超时（REST 部分接口全量查询较慢，给足时间）
DEFAULT_TIMEOUT = 60
QUICK_TIMEOUT = 15


# ------------------------------------------------------------
# 多账号配置加载
# ------------------------------------------------------------
def find_project_config() -> dict:
    """从当前目录向上查找 .archery.json 项目配置"""
    cur = Path.cwd()
    for d in [cur] + list(cur.parents):
        cfg = d / ".archery.json"
        if cfg.exists():
            try:
                # utf-8-sig 兼容 BOM（Windows 编辑器常见）
                data = json.loads(cfg.read_text(encoding="utf-8-sig"))
                data["_path"] = str(cfg)
                return data
            except Exception:
                pass
    return {}


def load_user_config() -> dict:
    """加载用户级配置 ~/.archery.json（可选）"""
    cfg = Path.home() / ".archery.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {}


def resolve_pat(cli_pat: str = None) -> tuple:
    """按优先级解析 PAT，返回 (pat, source描述)"""
    # 1. 命令行（会话级，最高优先级）
    if cli_pat:
        return cli_pat.strip(), "命令行 --pat（会话级）"
    # 2. 环境变量
    env = os.environ.get("ARCHERY_PAT", "").strip()
    if env:
        return env, "环境变量 ARCHERY_PAT"
    # 3. 项目配置 .archery.json
    proj = find_project_config()
    if proj.get("pat"):
        return str(proj["pat"]).strip(), f"项目配置 {proj.get('_path')}"
    return None, ""


def resolve_account(cli_pat: str = None, account: str = None) -> tuple:
    """解析 PAT + 账号标识。若项目配置含 accounts 账号表，可按 account 名选择。
    返回 (pat, source描述, account名)"""
    # 1. 会话级（命令行）
    if cli_pat:
        return cli_pat.strip(), "命令行 --pat（会话级）", account or "default"
    # 2. 环境变量
    env = os.environ.get("ARCHERY_PAT", "").strip()
    if env:
        return env, "环境变量 ARCHERY_PAT", account or "default"
    # 3. 项目配置
    proj = find_project_config()
    if proj:
        # 项目级账号表
        accounts = proj.get("accounts")
        if accounts and account:
            if account in accounts:
                return str(accounts[account]["pat"]).strip(), f"项目配置账号 {account}", account
        if accounts:
            # 账号表存在但未指定 -> 用默认账号
            default = proj.get("default_account")
            if default and default in accounts:
                return str(accounts[default]["pat"]).strip(), f"项目配置默认账号 {default}", default
            first = list(accounts.keys())[0]
            return str(accounts[first]["pat"]).strip(), f"项目配置账号 {first}", first
        if proj.get("pat"):
            return str(proj["pat"]).strip(), f"项目配置 {proj.get('_path')}", account or "default"
    # 4. 用户级配置
    user = load_user_config()
    if user.get("accounts"):
        accounts = user["accounts"]
        if account and account in accounts:
            return str(accounts[account]["pat"]).strip(), f"用户配置账号 {account}", account
        default = user.get("default_account")
        if default and default in accounts:
            return str(accounts[default]["pat"]).strip(), f"用户配置默认账号 {default}", default
        first = list(accounts.keys())[0]
        return str(accounts[first]["pat"]).strip(), f"用户配置账号 {first}", first
    # 5. 内置默认
    if DEFAULT_PAT:
        return DEFAULT_PAT, "脚本内置默认", account or "default"
    raise SystemExit(
        "未找到 PAT！请通过 --pat 参数、环境变量 ARCHERY_PAT、\n"
        "项目 .archery.json（含 accounts 账号表）或 ~/.archery.json 提供。\n"
        "获取方式：系统右上角头像 → Personal Access Tokens → 创建\n"
        "项目级示例 .archery.json：\n"
        "{\n"
        '  "accounts": {\n'
        '    "alice": {"pat": "arp_pat_...", "display": "Alice"}, \n'
        '    "bob":   {"pat": "arp_pat_...", "display": "Bob"}\n'
        "  },\n"
        '  "default_account": "alice"\n'
        "}"
    )


class ArcheryAPI:
    def __init__(self, pat: str = None, verify_ssl: bool = True):
        self.pat, self.pat_source, self.account = resolve_account(pat)
        self.session = requests.Session()
        self.session.verify = verify_ssl
        self.session.headers.update({
            "Authorization": f"Bearer {self.pat}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        })
        self._inst_cache = None

    # --------------------------------------------------------
    # 底层请求
    # --------------------------------------------------------
    def _req(self, method: str, path: str, params: dict = None, json_body: dict = None,
             timeout: int = DEFAULT_TIMEOUT) -> dict:
        """REST 请求，统一返回 JSON（含错误详情）"""
        try:
            r = self.session.request(method, BASE_URL + path, params=params,
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
            return detail
        return body

    def _get(self, path: str, params: dict = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
        return self._req("GET", path, params=params, timeout=timeout)

    def _post(self, path: str, data: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
        return self._req("POST", path, json_body=data, timeout=timeout)

    # --------------------------------------------------------
    # 认证与用户
    # --------------------------------------------------------
    def whoami(self) -> dict:
        """当前 PAT 对应的用户信息（验证认证是否有效）"""
        return self._get("/api/v1/user/current/", timeout=QUICK_TIMEOUT)

    # --------------------------------------------------------
    # 实例与资源
    # --------------------------------------------------------
    def instances(self, size: int = 100) -> dict:
        """实例列表（REST 用 size 参数，单页最多可返回指定数量）"""
        return self._get("/api/v1/instance/", {"size": size}, timeout=DEFAULT_TIMEOUT)

    def instance_resource(self, instance_name: str = None, instance_id: int = None,
                          resource_type: str = "database", db_name: str = None,
                          tb_name: str = None, schema_name: str = None) -> dict:
        """获取实例资源：database | schema | table | column
        需要 instance_id（数字）或 instance_name（会自动解析 ID）。
        返回 {count, result: [...]}（REST 格式）
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
        """通过 REST 实例列表查找实例 ID（size=500 一次拉取，缓存结果）"""
        if self._inst_cache is None:
            try:
                data = self.instances(size=500)
                results = data.get("results", [])
                self._inst_cache = {r.get("instance_name"): r.get("id") for r in results}
            except Exception:
                self._inst_cache = {}
        return self._inst_cache.get(instance_name)

    # --------------------------------------------------------
    # SQL 查询
    # --------------------------------------------------------
    def query(self, instance_name: str, db_name: str, sql_content: str,
              limit_num: int = 100) -> dict:
        """执行只读 SQL 查询（REST /api/v1/query/）"""
        return self._post("/api/v1/query/", {
            "instance_name": instance_name,
            "db_name": db_name,
            "sql_content": sql_content,
            "limit_num": limit_num,
        }, timeout=DEFAULT_TIMEOUT)

    # --------------------------------------------------------
    # SQL 检查
    # --------------------------------------------------------
    def sql_check(self, instance_id: int = None, instance_name: str = None,
                  db_name: str = None, full_sql: str = "") -> dict:
        """SQL 预检（REST /api/v1/workflow/sqlcheck/）"""
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
    def workflow_list(self, status: str = "workflow_finish", search: str = "",
                      engineer: str = "", group_name: str = "", db_name: str = "",
                      instance_id: int = None, start_time: str = "",
                      end_time: str = "", page: int = 1, page_size: int = 10) -> dict:
        """工单列表（REST，建议至少带一个筛选条件，否则全量查询慢）"""
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
        """工单详情"""
        return self._get(f"/api/v1/workflow/{workflow_id}", timeout=QUICK_TIMEOUT)

    def workflow_status(self, workflow_id: int) -> dict:
        """工单状态（从详情提取）"""
        return self.workflow_detail(workflow_id)

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
        """回滚 SQL（工单需已执行完成且开启备份）"""
        return self._post("/api/v1/workflow/rollback/", {
            "workflow_id": workflow_id,
        }, timeout=QUICK_TIMEOUT)

    def workflow_cancel(self, workflow_id: int, workflow_type: int = 2,
                        engineer: str = None, remark: str = "人工终止工单") -> dict:
        """终止工单（未执行）：适用于 waiting/review_pass/timingtask 等未执行状态。
        发起人/审核人可终止。engineer 缺省取当前 PAT 用户。
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
        """待审核清单（当前用户待审核的工单）"""
        if not engineer:
            me = self.whoami()
            engineer = me.get("username") or ""
        return self._post("/api/v1/workflow/auditlist/", {
            "engineer": engineer,
            "workflow_type": workflow_type,
            "page": page,
            "page_size": page_size,
        }, timeout=QUICK_TIMEOUT)


def main():
    parser = argparse.ArgumentParser(
        description="Archery SQL 审核平台 API 客户端（PAT 认证）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("action", choices=[
        "whoami", "workflow-list", "workflow-detail", "workflow-status",
        "workflow-log", "workflow-rollback", "workflow-cancel", "audit-list",
        "instances", "instance-resource", "query",
        "sql-check",
    ], help="要执行的操作")
    parser.add_argument("--pat", default=None, help="Personal Access Token（会话级，最高优先级）")
    parser.add_argument("--account", default=None, help="账号名（项目配置 accounts 表）")
    parser.add_argument("--id", type=int, help="工单 ID 或实例 ID")
    parser.add_argument("--workflow-type", type=int, default=2, help="工单类型 1=查询权限 2=SQL上线 3=数据归档")
    parser.add_argument("--status", default="workflow_finish", help="工单状态筛选（默认已结束，避免全量慢）")
    parser.add_argument("--search", default="", help="工单名称模糊搜索")
    parser.add_argument("--engineer", default="", help="发起人筛选")
    parser.add_argument("--group", default="", help="资源组筛选")
    parser.add_argument("--instance", default="", help="实例名")
    parser.add_argument("--db", default="", help="数据库名")
    parser.add_argument("--tb", default="", help="表名")
    parser.add_argument("--schema", default="", help="schema名")
    parser.add_argument("--resource-type", choices=["database", "schema", "table", "column"], default="database")
    parser.add_argument("--sql", default="", help="SQL 内容")
    parser.add_argument("--limit-num", type=int, default=100, help="查询行数上限")
    parser.add_argument("--start-time", default="", help="创建时间起 (2026-08-01T00:00:00)")
    parser.add_argument("--end-time", default="", help="创建时间止")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=10)
    # 终止参数
    parser.add_argument("--remark", default="人工终止工单", help="终止原因")

    args = parser.parse_args()
    api = ArcheryAPI(pat=args.pat)
    if args.account:
        api.account = args.account
    print(f"[认证] 使用 {api.pat_source}", file=sys.stderr)

    def _check(data):
        """打印 REST 返回（统一处理错误）"""
        if isinstance(data, dict) and data.get("_error"):
            print(json.dumps(data, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        return data

    try:
        result = None
        if args.action == "whoami":
            result = _check(api.whoami())
        elif args.action == "workflow-list":
            result = _check(api.workflow_list(
                status=args.status, search=args.search, engineer=args.engineer,
                group_name=args.group, db_name=args.db,
                instance_id=args.id,
                start_time=args.start_time, end_time=args.end_time,
                page=args.page, page_size=args.page_size,
            ))
        elif args.action == "workflow-detail":
            result = _check(api.workflow_detail(args.id))
        elif args.action == "workflow-status":
            result = _check(api.workflow_status(args.id))
        elif args.action == "workflow-log":
            result = _check(api.workflow_log(args.id, args.workflow_type, args.page, args.page_size))
        elif args.action == "workflow-rollback":
            result = _check(api.workflow_rollback(args.id))
        elif args.action == "workflow-cancel":
            result = _check(api.workflow_cancel(args.id, args.workflow_type, args.engineer, args.remark))
        elif args.action == "audit-list":
            result = _check(api.audit_list(args.engineer, args.workflow_type, args.page, args.page_size))
        elif args.action == "instances":
            result = _check(api.instances(size=args.page_size))
        elif args.action == "instance-resource":
            result = _check(api.instance_resource(
                instance_name=args.instance or None, instance_id=args.id,
                resource_type=args.resource_type, db_name=args.db,
                tb_name=args.tb, schema_name=args.schema,
            ))
        elif args.action == "query":
            result = _check(api.query(args.instance, args.db, args.sql, args.limit_num))
        elif args.action == "sql-check":
            result = _check(api.sql_check(
                instance_id=args.id, instance_name=args.instance,
                db_name=args.db, full_sql=args.sql,
            ))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except SystemExit:
        raise
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()