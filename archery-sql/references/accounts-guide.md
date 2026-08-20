# Archery SQL 平台 · 多账号配置说明

## 三种配置层级（优先级从高到低）

| 层级 | 存储位置 | 使用方式 | 适用场景 |
|---|---|---|---|
| **会话级** | 会话记忆（不落盘） | 调用时 `--pat arp_pat_xxx` | 临时使用某账号/一次性任务 |
| **项目级** | 项目根目录 `.archery.json` | 客户端自动向上查找 | 项目固定账号/多账号分工 |
| **用户级** | `~/.archery.json` | 客户端自动读取 | 个人常用账号跨项目复用 |

> ⚠️ **安全提示**：`.archery.json` 含敏感凭证，务必加入 `.gitignore`！

## 1. 会话级（推荐日常使用）

由 AI/脚本从会话记忆读取 PAT 并显式传入，凭证不落盘：

```bash
python archery_api.py whoami --pat "arp_pat_xxx"
python archery_api.py workflow-list --status workflow_manreviewing --pat "arp_pat_xxx"
```

## 2. 项目级（项目根目录 .archery.json）

### 单账号
```json
{
  "pat": "arp_pat_项目专用token",
  "note": "该项目默认使用的账号"
}
```

### 多账号（项目内不同角色）
```json
{
  "accounts": {
    "alice": { "pat": "arp_pat_alice的token", "display": "Alice Zhang" },
    "bob":   { "pat": "arp_pat_bob的token",   "display": "Bob Li" }
  },
  "default_account": "alice"
}
```
```bash
python archery_api.py whoami --account alice
python archery_api.py whoami --account bob
python archery_api.py whoami            # 默认账号 alice
```

## 3. 用户级（C:\Users\<用户名>\.archery.json）

个人常用账号，跨项目复用：
```json
{
  "accounts": {
    "jian.bj": { "pat": "arp_pat_...", "display": "Bian Jian" },
    "test":    { "pat": "arp_pat_...", "display": "测试账号" }
  },
  "default_account": "jian.bj"
}
```

## PAT 创建方式

1. 登录 https://archery.cn-pgcloud.com
2. 右上角头像 → **Personal Access Tokens**（/user/tokens/）
3. 创建 Token（格式：`arp_pat_...`），仅显示一次，请保存

## 优先级总结

`--pat 参数`（会话级）→ `环境变量 ARCHERY_PAT` → `项目 .archery.json`（accounts 或 pat）→ `用户 ~/.archery.json`（accounts）→ 内置默认（不推荐）