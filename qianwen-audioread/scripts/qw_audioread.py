# -*- coding: utf-8 -*-
"""
qw_audioread.py — 千问「音视频速读」客户端（纯标准库，零依赖）

已验证的 API（2026-08-22）:
  - api.qianwen.com/assistant/api/*          记录列表/文件夹/删除/已读（需 Cookie + x-platform + x-xsrf-token）
  - audio-api.qianwen.com/api/*              转写全文/导读/脑图/笔记/媒体（需 x-tw-from: tongyi）

用法见 SKILL.md 或 --help
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API_HOST = "https://api.qianwen.com"
AUDIO_HOST = "https://audio-api.qianwen.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".qianwen_audioread.json")

RECORD_STATUS = {10: "上传中", 20: "转写中", 30: "已完成", 33: "部分完成",
                 40: "转写失败", 41: "转写失败", 43: "已取消"}


# ---------------------------------------------------------------- 基础设施
def load_cookie(cli_cookie=None):
    if cli_cookie:
        return cli_cookie.strip()
    env = os.environ.get("QIANWEN_COOKIE", "").strip()
    if env:
        return env
    if os.path.exists(CONFIG_PATH):
        try:
            cfg = json.load(open(CONFIG_PATH, encoding="utf-8-sig"))
            ck = cfg.get("cookie", "").strip()
            if ck:
                return ck
        except Exception:
            pass
    sys.exit("未找到 Cookie。请通过 --cookie / 环境变量 QIANWEN_COOKIE / "
             f"配置文件 {CONFIG_PATH} 提供（参考 SKILL.md）")


def get_xsrf(cookie):
    m = re.search(r"XSRF-TOKEN=([^;]+)", cookie)
    if m:
        return m.group(1)
    req = urllib.request.Request("https://www.qianwen.com/",
                                 headers={"cookie": cookie, "user-agent": UA})
    resp = urllib.request.urlopen(req, timeout=30)
    for h in resp.headers.get_all("Set-Cookie") or []:
        if h.startswith("XSRF-TOKEN="):
            return h.split(";")[0].split("=", 1)[1]
    return ""


class Client:
    def __init__(self, cookie):
        self.cookie = cookie
        self.xsrf = get_xsrf(cookie)

    def _headers(self, for_audio=False):
        h = {
            "cookie": self.cookie + ("; XSRF-TOKEN=" + self.xsrf if self.xsrf else ""),
            "user-agent": UA,
            "referer": "https://www.qianwen.com/",
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://www.qianwen.com",
            "accept-language": "zh-CN,zh;q=0.9",
        }
        if for_audio:
            h["x-tw-from"] = "tongyi"
        else:
            h["x-platform"] = "pc_tongyi"
            h["x-xsrf-token"] = self.xsrf
        return h

    def _post(self, url, data, for_audio=False, timeout=60):
        req = urllib.request.Request(url, data=json.dumps(data).encode(),
                                     headers=self._headers(for_audio), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            return {"_http": e.code, "_body": body}

    def _get(self, url, timeout=60):
        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    # ------------------------------------------------ assistant API
    def whoami(self):
        return self._get(f"{API_HOST}/assistant/api/user/info/get?isLogin=&c=tongyi-web")

    def record_list(self, page=1, size=50, dir_id="0", status=None, show_name="",
                    order_desc=True):
        body = {
            "status": status or [10, 20, 30, 33, 40, 41, 43],
            "beginTime": "", "endTime": "", "showName": show_name,
            "dirIdStr": str(dir_id), "lang": "", "orderType": 0,
            "orderDesc": order_desc, "pageNo": page, "pageSize": size,
        }
        return self._post(f"{API_HOST}/assistant/api/record/list?c=tongyi-web", body)

    def all_records(self, max_pages=20, size=100, dir_id="0", scan_all_dirs=False):
        """遍历拉取全部记录，返回扁平列表。

        scan_all_dirs=True 时，递归遍历目录树（含子目录）下的所有记录，
        并为每条记录附加 _dirName（所属文件夹名）。
        """
        dir_names = self.dir_map() if scan_all_dirs else {}
        dirs = [str(dir_id)]
        if scan_all_dirs:
            dirs = sorted(dir_names.keys(), key=lambda x: (x != "0", len(x), x))
        out = []
        seen = set()
        for d_id in dirs:
            got = 0
            for p in range(1, max_pages + 1):
                d = self.record_list(page=p, size=size, dir_id=d_id)
                batches = (d.get("data") or {}).get("batchRecord") or []
                if not batches:
                    break
                for b in batches:
                    for r in b.get("recordList") or []:
                        if r.get("recordId") in seen:
                            continue
                        seen.add(r.get("recordId"))
                        r["_batchId"] = b.get("batchId")
                        r["_dirIdStr"] = d_id
                        if scan_all_dirs:
                            r["_dirName"] = dir_names.get(d_id, "")
                        out.append(r)
                        got += 1
                total = (d.get("data") or {}).get("total", 0)
                if got >= total:
                    break
            if not scan_all_dirs:
                break
        return out

    def dir_list(self):
        return self._post(f"{API_HOST}/assistant/api/record/dir/list/get?c=tongyi-web", {})

    def dir_map(self):
        """扁平化目录树，返回 {idStr: dirName}"""
        out = {}

        def walk(items):
            for item in items or []:
                d = item.get("dir") or {}
                if d.get("idStr") is not None:
                    out[str(d.get("idStr"))] = d.get("dirName") or ""
                walk(item.get("children"))

        walk((self.dir_list().get("data")) or [])
        return out

    def resolve_dir(self, name_or_id):
        """目录名或 idStr → idStr；找不到则报错并列出可用目录"""
        s = str(name_or_id)
        if s.isdigit():
            return s
        dm = self.dir_map()
        for idstr, name in dm.items():
            if name == s:
                return idstr
        sys.exit(f"未找到目录「{s}」，可用目录: " + ", ".join(dm.values()))

    def record_detail(self, gen_record_id, record_source="tingwu"):
        return self._post(f"{API_HOST}/assistant/api/record/detail/data/get?c=tongyi-web",
                          {"recordSource": record_source, "genRecordId": gen_record_id})

    def mark_read(self, record_ids):
        return self._post(f"{API_HOST}/assistant/api/record/read?c=tongyi-web",
                          {"recordIds": record_ids})

    def delete_records(self, record_ids):
        return self._post(f"{API_HOST}/assistant/api/record/task/delete?c=tongyi-web",
                          {"recordIds": record_ids})

    def delete_batch(self, batch_id):
        return self._post(f"{API_HOST}/assistant/api/record/task/batchDelete?c=tongyi-web",
                          {"batchId": batch_id})

    def cancel_task(self, record_ids):
        return self._post(f"{API_HOST}/assistant/api/record/task/cancel?c=tongyi-web",
                          {"recordIds": record_ids})

    # ------------------------------------------------ audio-api (听悟)
    def trans_result(self, trans_id):
        return self._post(f"{AUDIO_HOST}/api/trans/getTransResult?c=tongyi-web",
                          {"action": "getTransResult", "version": "1.0", "transId": trans_id},
                          for_audio=True)

    def lab_info(self, trans_id, content=None):
        content = content or ["labInfo", "labSummaryInfo", "labMindInfo"]
        return self._post(f"{AUDIO_HOST}/api/lab/getAllLabInfo?c=tongyi-web",
                          {"action": "getAllLabInfo", "content": content, "transId": trans_id},
                          for_audio=True)

    def trans_tag(self, trans_id):
        return self._post(f"{AUDIO_HOST}/api/tag/request?getTransTag&c=tongyi-web",
                          {"action": "getTransTag", "version": "1.0", "transId": trans_id},
                          for_audio=True)

    def note(self, trans_id):
        return self._post(f"{AUDIO_HOST}/api/doc/getTransDocEdit?c=tongyi-web",
                          {"action": "getTransDocEdit", "version": "1.0", "transId": trans_id},
                          for_audio=True)


def need_login_check(resp):
    if isinstance(resp, dict) and resp.get("code") == "TRS.NeedLogin":
        sys.exit("未登录或登录已过期（TRS.NeedLogin）。请更新 Cookie（参考 SKILL.md）")
    if isinstance(resp, dict) and resp.get("_http") == 401:
        sys.exit("401 未授权。请更新 Cookie（参考 SKILL.md）")


def find_record(client, rec_id, scan_all_dirs=True):
    """按 genRecordId 或 recordId 查找记录"""
    recs = client.all_records(scan_all_dirs=scan_all_dirs)
    for r in recs:
        if r.get("genRecordId") == rec_id or r.get("recordId") == rec_id:
            return r, recs
    return None, recs


def fmt_ts(ms):
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_ts_srt(ms):
    s, msec = divmod(ms, 1000)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"


# ---------------------------------------------------------------- 内容渲染
def extract_transcript(trans_result):
    """返回 [(speaker, start_ms, end_ms, text)] 段落列表"""
    data = trans_result.get("data") or {}
    need_login_check(trans_result)
    result_str = data.get("result") or "{}"
    try:
        result = json.loads(result_str)
    except Exception:
        return []
    paragraphs = []
    for pg in result.get("pg") or []:
        segs = []
        cur_spk, cur_bt, cur_et = None, None, None
        buf = []

        def flush():
            if buf:
                paragraphs.append((cur_spk, cur_bt or 0, cur_et or 0, "".join(buf)))

        for sc in pg.get("sc") or []:
            spk = sc.get("si")
            if spk != cur_spk and buf:
                flush()
                buf = []
                cur_bt = sc.get("bt")
            if cur_spk is None:
                cur_spk, cur_bt = spk, sc.get("bt")
            cur_spk, cur_et = spk, sc.get("et")
            buf.append(sc.get("tc") or "")
            # 句子切分：以标点结尾且长度足够则断句
            text = "".join(buf)
            if len(text) >= 40 and text.endswith(("。", "！", "？", "…", "，")):
                flush()
                buf, cur_bt = [], None
        flush()
    return paragraphs


def render_txt(paragraphs):
    return "\n\n".join(p[3] for p in paragraphs)


def render_md(trans_id, title, paragraphs):
    lines = [f"# {title or trans_id}", ""]
    cur = None
    for spk, bt, et, text in paragraphs:
        tag = f"说话人{spk}" if spk else "说话人"
        if tag != cur:
            lines.append(f"\n**{tag}** [{fmt_ts(bt)}]")
            cur = tag
        lines.append(text)
    return "\n".join(lines)


def render_srt(paragraphs):
    lines = []
    for i, (spk, bt, et, text) in enumerate(paragraphs, 1):
        lines += [str(i), f"{fmt_ts_srt(bt)} --> {fmt_ts_srt(et)}", text, ""]
    return "\n".join(lines)


def lab_cards(lab_resp):
    data = lab_resp.get("data") or {}
    return data.get("labCardsMap") or {}


def card_values(cards, key):
    """cards 顶层是分组（labInfo 等），按卡片 key 聚合全部 contentValues"""
    vals = []
    for group in cards.values():
        for c in group or []:
            if c.get("key") != key:
                continue
            for cont in c.get("contents") or []:
                vals.extend(cont.get("contentValues") or [])
    return vals


def render_summary(trans_id, title, cards):
    lines = [f"# 导读：{title or trans_id}", ""]
    kw = [v.get("value") for v in card_values(cards, "keyWordsExtractor") if v.get("value")]
    if kw:
        lines.append("## 关键词")
        lines.append("、".join(kw) + "\n")
    fs = card_values(cards, "fullSummary")
    if fs:
        lines.append("## 全文摘要")
        for v in fs:
            lines.append(v.get("value", "") + "\n")
    ag = card_values(cards, "agendaSummary")
    if ag:
        lines.append("## 议程摘要")
        for v in ag:
            lines.append(f"### {v.get('title', '')}")
            lines.append(v.get("value", "") + "\n")
    info = card_values(cards, "infoExtractor")
    if info:
        lines.append("## 重点内容")
        for v in info:
            ts = fmt_ts(v.get("time", 0)) if v.get("time") else ""
            lines.append(f"- [{ts}] {v.get('value', '')}")
        lines.append("")
    todo = card_values(cards, "actionExtractor")
    if todo:
        lines.append("## 智能待办")
        for v in todo:
            lines.append(f"- {v.get('value', '')}")
        lines.append("")
    return "\n".join(lines)


def mindmap_to_md(node, depth=0):
    lines = []
    content = node.get("content")
    if content:
        lines.append("  " * depth + ("- " if depth else "# ") + content)
    for ch in node.get("children") or []:
        lines.extend(mindmap_to_md(ch, depth + 1))
    return lines


def render_mindmap(cards):
    lines = []
    for v in card_values(cards, "mindMapSummary"):
        tree = v.get("json")
        if tree:
            lines.extend(mindmap_to_md(tree))
    return "\n".join(lines) if lines else ""


def mindmap_json(cards):
    out = []
    for v in card_values(cards, "mindMapSummary"):
        if v.get("json"):
            out.append(v["json"])
    return out


# ---------------------------------------------------------------- 命令
def cmd_whoami(c, args):
    r = c.whoami()
    d = r.get("data") or {}
    if d.get("userId"):
        print(f"登录有效  userId={d['userId']}  accountType={d.get('accountType')}")
    else:
        print("未登录:", json.dumps(r, ensure_ascii=False)[:200])


def cmd_folders(c, args):
    # 统计每个目录的记录数
    counts = {}
    try:
        for r in c.all_records(scan_all_dirs=True, size=100):
            d = r.get("_dirIdStr", "0")
            counts[d] = counts.get(d, 0) + 1
    except Exception:
        pass

    def walk(items, depth):
        for item in items or []:
            d = item.get("dir") or {}
            idstr = str(d.get("idStr", ""))
            indent = "  " * depth
            n = counts.get(idstr, 0)
            print(f"{indent}{d.get('dirName', '?')}  (idStr={idstr}, 记录数={n})")
            walk(item.get("children"), depth + 1)

    walk(c.dir_list().get("data") or [], 0)


def cmd_list(c, args):
    type_filter = {"audio", "video", "all"} & {args.type} if args.type != "all" else None
    if args.dir:
        dir_id = c.resolve_dir(args.dir)
        recs = c.all_records(dir_id=dir_id)
    else:
        recs = c.all_records(scan_all_dirs=True)
    dir_names = c.dir_map()
    rows = []
    for r in recs:
        if type_filter and r.get("recordType") not in type_filter:
            continue
        if args.status is not None and r.get("recordStatus") != args.status:
            continue
        rows.append(r)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    print(f"共 {len(rows)} 条记录" + ("" if args.dir else "（全部目录）"))
    print(f"{'genRecordId':<18} {'类型':<6} {'状态':<8} {'时长':<9} {'目录':<14} 标题")
    for r in rows:
        dur = fmt_ts(r.get("recordDuration", 0) * 1000) if r.get("recordDuration") else "-"
        st = RECORD_STATUS.get(r.get("recordStatus"), r.get("recordStatus"))
        dirname = r.get("_dirName") or dir_names.get(str(r.get("dirIdStr") or r.get("_dirIdStr") or "0"), "")
        print(f"{r.get('genRecordId',''):<18} {r.get('recordType',''):<6} {st:<8} "
              f"{dur:<9} {dirname:<14} {r.get('recordTitle','')}")


def cmd_detail(c, args):
    rec, _ = find_record(c, args.id)
    if rec:
        keys = ["recordId", "genRecordId", "recordTitle", "recordType", "recordStatus",
                "recordDuration", "fileSize", "recordLang", "recordSource", "taskType",
                "gmtCreate", "dirIdStr", "recordTags"]
        dir_names = c.dir_map()
        for k in keys:
            if k in rec:
                v = rec[k]
                if k == "gmtCreate":
                    v = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v / 1000))
                if k == "recordStatus":
                    v = f"{v} ({RECORD_STATUS.get(v, '?')})"
                if k == "dirIdStr":
                    v = f"{v} ({dir_names.get(str(v), '?')})"
                print(f"{k}: {v}")
    else:
        print("record/list 中未找到该记录（可能已删除），尝试直接查询转写内容…")
    tr = c.trans_result(args.id)
    d = tr.get("data") or {}
    if d.get("transId"):
        print(f"\n[转写服务] taskId={d.get('taskId')} status={d.get('status')} "
              f"时长={fmt_ts(d.get('duration',0))} 字数={d.get('wordCount')}")


def cmd_transcript(c, args):
    tr = c.trans_result(args.id)
    need_login_check(tr)
    paras = extract_transcript(tr)
    if not paras:
        sys.exit("无转写内容（可能仍在处理中或 ID 错误）")
    title = args.title or ""
    if args.format == "srt":
        print(render_srt(paras))
    elif args.format == "md":
        print(render_md(args.id, title, paras))
    else:
        print(render_txt(paras))


def cmd_summary(c, args):
    lab = c.lab_info(args.id)
    need_login_check(lab)
    cards = lab_cards(lab)
    print(render_summary(args.id, args.title, cards))


def cmd_mindmap(c, args):
    lab = c.lab_info(args.id)
    need_login_check(lab)
    cards = lab_cards(lab)
    if args.json:
        print(json.dumps(mindmap_json(cards), ensure_ascii=False, indent=1))
    else:
        print(render_mindmap(cards))


def cmd_note(c, args):
    r = c.note(args.id)
    need_login_check(r)
    print((r.get("data") or {}).get("content") or "(无笔记)")


def cmd_media(c, args):
    tr = c.trans_result(args.id)
    need_login_check(tr)
    d = tr.get("data") or {}
    urls = {}
    if d.get("playback"):
        urls["音频/回放"] = d["playback"]
    if d.get("playVideoUrl"):
        urls["视频"] = d["playVideoUrl"]
    for name, u in urls.items():
        print(f"{name}: {u}")
    if args.download and urls:
        os.makedirs(args.download, exist_ok=True)
        for name, u in urls.items():
            ext = ".mp4" if "视频" in name else ".m4a"
            out = os.path.join(args.download, f"{args.id}{ext}")
            print(f"下载 {name} → {out}")
            req = urllib.request.Request(u, headers={"user-agent": UA})
            with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            print(f"  完成 {os.path.getsize(out)} bytes")


def cmd_export(c, args):
    outdir = args.out or f"export_{args.id}"
    os.makedirs(outdir, exist_ok=True)
    parts = set(args.parts.split(",")) if args.parts else \
        {"transcript", "summary", "mindmap", "note", "media"}
    rec, _ = find_record(c, args.id)
    title = (rec or {}).get("recordTitle") or args.id
    safe_title = re.sub(r'[\\/:*?"<>|\s]+', "_", title)[:40]
    written = []

    tr = c.trans_result(args.id)
    need_login_check(tr)

    if "transcript" in parts:
        paras = extract_transcript(tr)
        for fmt, renderer in (("txt", lambda: render_txt(paras)),
                              ("md", lambda: render_md(args.id, title, paras)),
                              ("srt", lambda: render_srt(paras))):
            fp = os.path.join(outdir, f"{safe_title}_原文.{fmt}")
            open(fp, "w", encoding="utf-8").write(renderer())
            written.append(fp)
    lab = None
    if parts & {"summary", "mindmap"}:
        lab = c.lab_info(args.id)
        cards = lab_cards(lab)
        if "summary" in parts:
            fp = os.path.join(outdir, f"{safe_title}_导读.md")
            open(fp, "w", encoding="utf-8").write(render_summary(args.id, title, cards))
            written.append(fp)
        if "mindmap" in parts:
            mm_md = render_mindmap(cards)
            if mm_md:
                fp = os.path.join(outdir, f"{safe_title}_脑图.md")
                open(fp, "w", encoding="utf-8").write(mm_md)
                written.append(fp)
            mm_json = mindmap_json(cards)
            if mm_json:
                fp = os.path.join(outdir, f"{safe_title}_脑图.json")
                open(fp, "w", encoding="utf-8").write(json.dumps(mm_json, ensure_ascii=False, indent=1))
                written.append(fp)
    if "note" in parts:
        nr = c.note(args.id)
        content = (nr.get("data") or {}).get("content") or ""
        if content:
            fp = os.path.join(outdir, f"{safe_title}_笔记.md")
            open(fp, "w", encoding="utf-8").write(content)
            written.append(fp)
    if "media" in parts:
        d = tr.get("data") or {}
        fp = os.path.join(outdir, f"{safe_title}_媒体链接.txt")
        lines = []
        if d.get("playback"):
            lines.append("音频/回放: " + d["playback"])
        if d.get("playVideoUrl"):
            lines.append("视频: " + d["playVideoUrl"])
        open(fp, "w", encoding="utf-8").write("\n".join(lines) or "(无媒体)")
        written.append(fp)
    for w in written:
        print("已导出:", w)
    print(f"\n共 {len(written)} 个文件 → {os.path.abspath(outdir)}")


def cmd_delete(c, args):
    if args.batch:
        r = c.delete_batch(args.batch)
        print("batchDelete:", json.dumps(r, ensure_ascii=False)[:200])
        return
    ids = []
    for rid in args.ids:
        if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", rid):
            ids.append(rid)
            continue
        rec, _ = find_record(c, rid)
        if not rec:
            print(f"跳过 {rid}：未找到对应记录")
            continue
        ids.append(rec["recordId"])
        print(f"解析 {rid} → recordId={rec['recordId']} ({rec.get('recordTitle')})")
    if not ids:
        sys.exit("没有可删除的记录")
    if not args.yes:
        ans = input(f"确认删除 {len(ids)} 条记录? (yes/NO) ").strip().lower()
        if ans not in ("y", "yes"):
            sys.exit("已取消")
    r = c.delete_records(ids)
    print("delete:", json.dumps(r, ensure_ascii=False)[:200])


def cmd_watch(c, args):
    """轮询等待新记录出现（配合浏览器手动上传使用）"""
    before = {r.get("recordId") for r in c.all_records()}
    print(f"当前记录数 {len(before)}，等待新记录出现（浏览器上传后自动检测）…")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        time.sleep(args.interval)
        cur = c.all_records()
        new = [r for r in cur if r.get("recordId") not in before]
        if new:
            for r in new:
                st = RECORD_STATUS.get(r.get("recordStatus"), r.get("recordStatus"))
                print(f"[新记录] {r.get('recordTitle')}  genRecordId={r.get('genRecordId')} "
                      f"状态={st}")
                if r.get("recordStatus") == 30:
                    print("转写完成！")
                    return
            print("   仍在处理，继续等待…")
    sys.exit("超时，未检测到新记录")


VIDEO_EXTS = {"mp4", "wmv", "m4v", "flv", "rmvb", "mov", "mkv", "webm", "avi", "mpeg", "3gp", "dat"}
AUDIO_EXTS = {"mp3", "wav", "m4a", "wma", "aac", "ogg", "amr", "flac", "aiff"}


def cmd_upload(c, args):
    """纯 HTTP 上传音视频并转写（已验证链路，无需签名/浏览器）"""
    fpath = os.path.abspath(args.file)
    if not os.path.exists(fpath):
        sys.exit(f"文件不存在: {fpath}")
    # 目标目录：支持目录名或 idStr
    dir_id = c.resolve_dir(args.dir) if args.dir else "0"
    fsize = os.path.getsize(fpath)
    fname = os.path.basename(fpath)
    show_name = os.path.splitext(fname)[0]
    ext = os.path.splitext(fname)[1].lstrip(".").lower()
    if ext not in VIDEO_EXTS | AUDIO_EXTS:
        sys.exit(f"不支持的格式 .{ext}，支持: 音频 {sorted(AUDIO_EXTS)} / 视频 {sorted(VIDEO_EXTS)}")
    is_video = 1 if ext in VIDEO_EXTS else 0
    ctype = ("video/" if is_video else "audio/") + (ext if ext != "mp3" else "mpeg")
    print(f"[0] 上传: {fname} ({fsize/1048576:.1f} MB, {'视频' if is_video else '音频'})")

    # Step 1: 获取上传凭证（putLink 预签名，免签名实现）
    token_body = {
        "taskType": "local", "useSts": 0, "fileSize": fsize,
        "dirIdStr": dir_id,
        "fileContentType": ctype, "bizTerminal": "web",
        "tag": {"showName": show_name, "fileFormat": ext, "fileType": "local",
                "lang": args.lang or "cn", "roleSplitNum": args.speakers,
                "translateSwitch": 0, "transTargetValue": 0,
                "originalTag": json.dumps({"isVideo": is_video}), "client": "web"}
    }
    d = c._post(f"{API_HOST}/assistant/api/record/oss/token/get?c=tongyi-web", token_body)
    if not d.get("success"):
        code = d.get("errorCode", "")
        if "StorageInsufficient" in code:
            sys.exit("失败：剩余存储空间不足，请先删除旧记录或升级容量")
        if "TransTimeInsufficient" in code:
            sys.exit("失败：剩余转写时长不足")
        sys.exit("获取上传凭证失败: " + json.dumps(d, ensure_ascii=False)[:300])
    data = d["data"]
    put_link = data.get("putLink")
    get_link = data.get("getLink")
    gen_id = data.get("genRecordId")
    record_id = data.get("recordId")
    if not put_link:
        sys.exit("服务端未返回 putLink（可能需要 STS 方式），请反馈")
    print(f"[1] 凭证已获取  genRecordId={gen_id}")

    # Step 2: PUT 文件到预签名链接
    print("[2] 上传文件中…")
    file_bytes = open(fpath, "rb").read()
    req = urllib.request.Request(put_link, data=file_bytes, method="PUT", headers={
        "content-type": ctype, "x-tw-from": "tongyi", "user-agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}")
    except Exception as e:
        c.delete_records([record_id])  # 清理占位记录
        sys.exit(f"文件上传失败: {e}")
    print("[3] 文件已上传，启动转写…")

    # Step 3: record/start
    start_body = {
        "taskType": "local",
        "tingwuRequest": {"fileLink": get_link, "transId": gen_id, "fileSize": fsize},
        "bizTerminal": "web", "dirIdStr": dir_id,
    }
    d = c._post(f"{API_HOST}/assistant/api/record/start?c=tongyi-web", start_body)
    if not d.get("success"):
        sys.exit("启动转写失败: " + json.dumps(d, ensure_ascii=False)[:300])
    print(f"[4] 转写任务已启动  genRecordId={gen_id}")

    # Step 4: 轮询（除非 --no-wait）
    if args.no_wait:
        print("（--no-wait：不等待，稍后用 list 查看）")
        return
    print("[5] 等待转写完成…")
    for i in range(args.timeout // 5):
        time.sleep(5)
        lst = c.record_list(size=30)
        for b in (lst.get("data") or {}).get("batchRecord") or []:
            for r in b.get("recordList") or []:
                if r.get("genRecordId") == gen_id:
                    st = r.get("recordStatus")
                    if st == 30:
                        print(f"[完成] 转写成功！标题={r.get('recordTitle')} "
                              f"时长={fmt_ts((r.get('recordDuration') or 0)*1000)}")
                        print(f"       genRecordId={gen_id}（可用 export/transcript/summary 导出）")
                        return
                    if st in (40, 41, 43):
                        sys.exit(f"转写失败/取消 (status={st})")
    sys.exit(f"等待超时（{args.timeout}秒），任务可能仍在处理，用 list 查看状态")


def main():
    p = argparse.ArgumentParser(description="千问音视频速读客户端")
    p.add_argument("--cookie", help="浏览器 Cookie 字符串（默认读环境变量/配置文件）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="验证登录态")
    sub.add_parser("folders", help="文件夹列表")

    sp = sub.add_parser("list", help="记录列表")
    sp.add_argument("--type", default="all", choices=["audio", "video", "all"])
    sp.add_argument("--dir", default=None, help="目录名或 idStr；省略则列出全部目录")
    sp.add_argument("--status", type=int, default=None)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("detail", help="记录详情")
    sp.add_argument("id", help="genRecordId 或 recordId")

    sp = sub.add_parser("transcript", help="导出转写原文")
    sp.add_argument("id")
    sp.add_argument("--format", default="txt", choices=["txt", "srt", "md"])
    sp.add_argument("--title", default="")

    sp = sub.add_parser("summary", help="导出导读")
    sp.add_argument("id")
    sp.add_argument("--title", default="")

    sp = sub.add_parser("mindmap", help="导出脑图")
    sp.add_argument("id")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("note", help="查看笔记")
    sp.add_argument("id")

    sp = sub.add_parser("media", help="媒体链接/下载")
    sp.add_argument("id")
    sp.add_argument("--download", help="下载到指定目录")

    sp = sub.add_parser("export", help="一键导出全部")
    sp.add_argument("id")
    sp.add_argument("--parts", help="逗号分隔: transcript,summary,mindmap,note,media")
    sp.add_argument("--out", help="输出目录")

    sp = sub.add_parser("delete", help="删除记录")
    sp.add_argument("ids", nargs="*", help="recordId(uuid) 或 genRecordId")
    sp.add_argument("--batch", help="按 batchId 删除")
    sp.add_argument("--yes", action="store_true", help="跳过确认")

    sp = sub.add_parser("watch", help="轮询等待新记录（配合浏览器上传）")
    sp.add_argument("--interval", type=int, default=10)
    sp.add_argument("--timeout", type=int, default=1800)

    sp = sub.add_parser("upload", help="上传音视频并转写（纯 HTTP）")
    sp.add_argument("file", help="音视频文件路径")
    sp.add_argument("--dir", default="0", help="目标文件夹名称或 idStr，默认 0（默认文件夹）")
    sp.add_argument("--lang", default="cn", help="语言: cn/en/ja/yue/fspk/auto，默认 cn")
    sp.add_argument("--speakers", type=int, default=-1,
                    help="说话人: -1不区分/1单人演讲/2两人对话/0多人讨论")
    sp.add_argument("--no-wait", action="store_true", help="启动后不等待转写完成")
    sp.add_argument("--timeout", type=int, default=1800, help="等待转写完成的超时秒数")

    args = p.parse_args()
    c = Client(load_cookie(args.cookie))
    {"whoami": cmd_whoami, "folders": cmd_folders, "list": cmd_list,
     "detail": cmd_detail, "transcript": cmd_transcript, "summary": cmd_summary,
     "mindmap": cmd_mindmap, "note": cmd_note, "media": cmd_media,
     "export": cmd_export, "delete": cmd_delete, "watch": cmd_watch,
     "upload": cmd_upload}[args.cmd](c, args)


if __name__ == "__main__":
    main()
