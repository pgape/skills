---
name: qianwen-audioread
description: "千问(qianwen.com)音视频速读管理：上传音视频转文字、查看记录列表、导出（原文/导读/脑图/笔记/音视频，多格式）、删除记录。TRIGGER when: 用户要上传音视频转写/转文字、查看或管理千问音视频速读记录、导出转写原文/导读/脑图/笔记、下载速读记录里的音视频、删除速读记录，或明确提到 qianwen-audioread。DO NOT TRIGGER when: 与千问音视频速读无关的任务（纯 API 调用用 qianwen-text，登录配置参考 qianwen-ops-auth）。"
---

# 千问「音视频速读」Skill

操作 qianwen.com 的音视频速读功能（转写、管理、导出、删除）。脚本位于本目录 `scripts/`，Python 3.8+ 标准库，无第三方依赖（上传功能除外）。

## 前置条件

**Cookie 认证**（见「认证」节）。本 skill 纯 Python 标准库，**无第三方依赖**——上传、导出、删除全部走纯 HTTP，无需浏览器或 Playwright。

## 认证

登录态由 `tongyi_sso_ticket` + `tongyi_sso_ticket_hash` 两个 Cookie 维持（配合风控类
`_qk_bx_*`/`tfstk`/`isg`，约 24h 轮换）。**用户提供方式**：在已登录的千问页面，
DevTools → 任意请求 → 复制 Cookie 请求头整串（或 Copy as cURL）。

Cookie 提供优先级：`--cookie` 参数 > 环境变量 `QIANWEN_COOKIE` > 配置文件
`~/.qianwen_audioread.json`（格式 `{"cookie": "..."}`）。

写入配置文件示例（将 `<COOKIE>` 替换为用户提供的值）：

```powershell
python -c "import json,os; json.dump({'cookie': '''<COOKIE>'''}, open(os.path.expanduser('~/.qianwen_audioread.json'),'w',encoding='utf-8'), ensure_ascii=False)"
```

验证登录：`python scripts/qw_audioread.py whoami` → 输出 `登录有效 userId=...`。
若报 `401`/`TRS.NeedLogin`：提示用户更新 Cookie。**绝不回显或打印 Cookie 明文。**

## 命令速查

```
python scripts/qw_audioread.py <命令>
```

| 命令 | 说明 |
|---|---|
| `whoami` | 验证登录态 |
| `folders` | 目录树（含 idStr 与各目录记录数） |
| `list [--type audio\|video\|all] [--dir 目录名或idStr] [--status N] [--json]` | 记录列表。**默认扫描全部目录**并显示所属文件夹；`--dir` 按目录过滤（支持目录名，如 `--dir 直播录音`） |
| `detail <id>` | 记录详情（id 可用 genRecordId 或 recordId，含所属目录名） |
| `transcript <id> [--format txt\|srt\|md]` | 转写原文 |
| `summary <id>` | 导读（关键词/全文摘要/议程摘要/重点/待办） |
| `mindmap <id> [--json]` | 脑图（markdown 缩进树 或 JSON） |
| `note <id>` | 用户笔记 |
| `media <id> [--download 目录]` | 音视频链接 / 下载 |
| `export <id> [--parts transcript,summary,mindmap,note,media] [--out 目录]` | 一键导出（默认全部，原文同时出 txt/md/srt） |
| `delete <id...> [--batch batchId] [--yes]` | 删除记录（不可恢复，默认需交互确认） |
| `upload <文件> [--dir 目录名或idStr] [--lang cn] [--speakers -1] [--no-wait]` | 上传音视频并转写（纯 HTTP，自动等完成），`--dir` 可指定目标文件夹 |
| `watch [--interval 10] [--timeout 1800]` | 轮询等待新记录出现 |

**目录说明**：记录分散在多个目录下（`POST /assistant/api/record/dir/list/get`）。
`list` 不带 `--dir` 时遍历所有目录；带 `--dir` 时只看该目录。目录参数既可传
`idStr`（数字）也可传目录名（自动解析）。上传时 `--dir` 同样支持目录名。

记录状态码：10 上传中 / 20 转写中 / 30 已完成 / 33 部分完成 / 40,41 失败 / 43 已取消。

## 上传音视频（转文字）

**纯 HTTP 实现，已验证，无需浏览器**。链路（逆向自前端，2026-08-22 实测成功）：

1. `POST api.qianwen.com/assistant/api/record/oss/token/get`（`useSts:0`）→ 返回预签名 `putLink`
2. `PUT <putLink>` 直接上传文件体（带 `x-tw-from: tongyi` 头）
3. `POST api.qianwen.com/assistant/api/record/start`（`tingwuRequest:{fileLink,transId,fileSize}`）→ 启动转写
4. 轮询 `record/list` 等待 `recordStatus=30`（完成）

```
python scripts/qw_audioread.py upload <音视频文件> [--dir 文件夹idStr] [--lang cn] [--speakers -1] [--no-wait]
```

- 支持格式：音频 `.mp3 .wav .m4a .wma .aac .ogg .amr .flac .aiff`；视频 `.mp4 .wmv .m4v .flv .rmvb .mov .mkv .webm .avi .mpeg .3gp .dat`
- `--lang`：`cn`中文 / `en`英文 / `ja`日文 / `yue`粤语 / `fspk`中英自由说 / `auto`自动
- `--speakers`：`-1`不区分发言人 / `1`单人演讲 / `2`两人对话 / `0`多人讨论
- 默认上传后自动等待转写完成；`--no-wait` 则启动后立即返回
- 常见错误：`TINGWU.TIG.StorageInsufficient`（存储空间不足，需删旧记录）、`TINGWU.TIG.TransTimeInsufficient`（转写时长不足）

## 导出说明

`export` 一次性产出（文件名带记录标题）：
- 原文：`_原文.txt` / `_原文.md`（带说话人与时间戳）/ `_原文.srt`（字幕）
- 导读：`_导读.md`（关键词/全文摘要/议程摘要/重点内容/智能待办）
- 脑图：`_脑图.md`（缩进树）+ `_脑图.json`（原始树结构，可导入脑图工具）
- 笔记：`_笔记.md`（仅有用户笔记时生成）
- 媒体：`_媒体链接.txt`（音频/视频的带签名 OSS 链接，约 24h 有效；需要文件时用 `media --download`）

## API 备忘（逆向自前端，2026-08-22 验证）

- 业务 host：`api.qianwen.com`（assistant/record 类，需 `x-platform: pc_tongyi` + `x-xsrf-token`）
- 转写内容：`audio-api.qianwen.com`（听悟，需 `x-tw-from: tongyi`，body 形如
  `{"action":"getTransResult","version":"1.0","transId":...}`；transId = genRecordId）
- 记录列表：`POST /assistant/api/record/list`（`pageNo/pageSize/dirIdStr/status` 数组）
- 删除：`POST /assistant/api/record/task/delete`（`{"recordIds":[uuid...]}`）；
  按批：`/assistant/api/record/task/batchDelete`（`{"batchId":...}`）
- 导读/脑图：`POST /api/lab/getAllLabInfo`，content 用
  `["labInfo","labSummaryInfo","labMindInfo"]`；卡片在 `data.labCardsMap` 的分组数组内，
  按卡片 `key` 聚合 `contents[].contentValues[]`
- 转写全文：`POST /api/trans/getTransResult`，正文在 `data.result`（JSON 字符串，
  `pg[].sc[]` 逐词，`si`=说话人 `bt/et`=毫秒 `tc`=文本）
- **401 排查**：页面级登录正常但 API 401 → 缺 `x-xsrf-token`（先从页面取
  `XSRF-TOKEN` Cookie）；仍 401 → Cookie 过期，让用户重新提供
- 上传用 `oss/token/get`（`useSts:0`）拿预签名 `putLink`，PUT 后调 `record/start`；
  `zhiwen-api.qianwen.com/zhiwen/api/v2/*`（旧版 task 详情）需要 baxia 签名，勿用，
  一律走上述 `api.qianwen.com/assistant/api/*` 新链路

## 安全

- Cookie 等价账号凭证：只存配置文件/环境变量，**绝不**写入代码、日志或回显
- 删除操作先列清单并确认（除非 `--yes`）；媒体链接含签名参数，勿外泄
