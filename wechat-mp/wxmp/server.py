#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最小 MCP 服务（stdio + 换行分隔的 JSON-RPC 2.0）。

只暴露三个工具：
    draft_push  把 html/md 投进草稿箱（可选按标题覆盖旧草稿）
    check       体检：取 token、查草稿总数
    list_drafts 列最近草稿标题

不依赖任何第三方 MCP SDK，标准库即可跑。
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

from . import api

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "wechat-mp-mcp", "version": "0.1.0"}

TOOLS = [
    {
        "name": "draft_push",
        "description": (
            "把一篇 html 或 markdown 文章写进微信公众号草稿箱。"
            "只写草稿，绝不发布。正文图片会上传换成微信图床地址，"
            "封面会作为永久素材上传。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "html 或 md 文件的绝对路径"},
                "title": {"type": "string", "description": "标题，≤32 字；不填取 <h1> 或文件名"},
                "cover": {"type": "string", "description": "封面图路径，建议 2.35:1；不填读配置 default_cover"},
                "author": {"type": "string", "description": "作者，≤16 字；不填读配置"},
                "digest": {"type": "string", "description": "摘要，≤120 字；不填由微信自动截取"},
                "update_existing": {
                    "type": "boolean",
                    "description": "true 时先按标题查重，命中则原地更新，未命中才新建；默认 false（总是新建）",
                    "default": False,
                },
            },
            "required": ["file"],
        },
    },
    {
        "name": "check",
        "description": "体检凭证与权限：取 access_token、查草稿总数。不写任何内容。返回当前出口 IP，便于排查白名单。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_drafts",
        "description": "列出最近的草稿标题（用于确认某篇是否已投过、避免重复）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数，默认 20，上限 50", "default": 20}
            },
        },
    },
]


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def _cfg() -> dict:
    # 优先级：环境变量 > ./config.json > ~/.config/wechat-mp-draft/config.json
    return api.load_config(None)


def tool_check(_args: dict) -> dict:
    cfg = _cfg()
    ip = api.egress_ip()
    token = api.get_token(cfg, force=True)
    q = urllib.parse.quote(token)
    total = api._http(f"{api.API_BASE}/cgi-bin/draft/count?access_token={q}").get("total_count")
    return _ok(
        "凭证可用。\n"
        f"access_token：获取成功（稳定版接口）\n"
        f"草稿总数：{total}\n"
        f"当前出口 IP：{ip}\n"
        "提示：该 IP 必须在开发者平台「API IP白名单」里，否则报 40164。"
    )


def tool_list_drafts(args: dict) -> dict:
    cfg = _cfg()
    limit = max(1, min(int(args.get("limit") or 20), 50))
    token = api.get_token(cfg)
    items = api.list_drafts(token, 0, limit)
    if not items:
        return _ok("草稿箱是空的。")
    rows = []
    for i, it in enumerate(items, 1):
        news = (it.get("content") or {}).get("news_item") or []
        title = news[0].get("title") if news else "(无标题)"
        rows.append(f"{i}. {title}  [{it.get('media_id', '')}]")
    return _ok(f"最近 {len(items)} 条草稿：\n" + "\n".join(rows))


def tool_draft_push(args: dict) -> dict:
    path = Path(str(args.get("file", ""))).expanduser()
    if not args.get("file"):
        return _err("缺少参数 file：请传 html 或 md 文件的绝对路径。")
    if not path.is_file():
        return _err(f"文件不存在：{path}")
    if path.suffix.lower() == ".md":
        ns = SimpleNamespace(
            html=None,
            md=str(path),
            title=args.get("title"),
            author=args.get("author"),
            digest=args.get("digest"),
            cover=args.get("cover"),
        )
    else:
        ns = SimpleNamespace(
            html=str(path),
            md=None,
            title=args.get("title"),
            author=args.get("author"),
            digest=args.get("digest"),
            cover=args.get("cover"),
        )

    cfg = _cfg()
    body, base_dir = api.load_body(ns)
    token = api.get_token(cfg)
    payload = api.build_articles(ns, cfg, token, body, base_dir)
    title = payload["articles"][0]["title"]

    if args.get("update_existing"):
        existing = api.find_draft_by_title(token, title)
        if existing:
            api.update_draft(token, existing, payload["articles"])
            return _ok(f"已命中同名草稿并原地更新。\n标题：{title}\nmedia_id：{existing}\n未发布。")

    data = api._http(
        f"{api.API_BASE}/cgi-bin/draft/add?access_token={urllib.parse.quote(token)}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    media_id = data.get("media_id", "")
    return _ok(f"已写入草稿箱。\n标题：{title}\nmedia_id：{media_id}\n请在后台人工发表。")


HANDLERS = {
    "draft_push": tool_draft_push,
    "check": tool_check,
    "list_drafts": tool_list_drafts,
}


def _rpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")

    if msg_id is None:  # 通知，不需要回包
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = HANDLERS.get(name)
        if not handler:
            return _rpc_error(msg_id, -32602, f"未知工具：{name}")

        try:
            result = handler(args)
        except api.WeChatError as e:
            hint = api.hint_for(e.code)
            text = f"微信接口报错：code={e.code} {e}"
            if hint:
                text += f"\n建议：{hint}"
            if e.code in (40164, 61004, 89503):
                text += f"\n当前出口 IP：{api.egress_ip()}"
            result = _err(text)
        except SystemExit as e:  # api 层用 sys.exit 抛校验错误，这里兜住
            result = _err(str(e.code) if not isinstance(e.code, int) else "参数校验未通过。")
        except Exception as e:  # noqa: BLE001
            result = _err(f"执行失败：{type(e).__name__}: {e}")

        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    return _rpc_error(msg_id, -32601, f"不支持的方法：{method}")


def main() -> int:
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = _rpc_error(None, -32700, "解析失败：不是合法 JSON")
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
