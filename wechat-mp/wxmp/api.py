#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公众号草稿箱投递（官方接口路线）

用法：
    export WECHAT_MP_APPID='wx...'
    export WECHAT_MP_APPSECRET='...'

    # 1) 只体检，不写草稿：验证权限 / 白名单 / token
    python3 -m wxmp.api --check

    # 2) 真实投递
    python3 -m wxmp.api --html article.html --title "标题" --cover cover.png

设计约束：
    - 凭证只从环境变量或本地配置文件读取，绝不硬编码、不打印。
    - 只调用草稿箱接口，代码里不存在任何发布/群发调用。
    - 仅依赖 Python 标准库（图片超限时借用 macOS 自带 sips 压缩，可用可不用）。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API_BASE = "https://api.weixin.qq.com"
CACHE_DIR = Path.home() / ".cache" / "wechat-mp-draft"
TOKEN_CACHE = CACHE_DIR / "token.json"

MAX_TITLE = 32
MAX_AUTHOR = 16
MAX_DIGEST = 120
MAX_CONTENT_CHARS = 20000
MAX_CONTENT_BYTES = 1024 * 1024
MAX_IMG_BYTES = 1024 * 1024  # uploadimg 接口硬限制：1MB


class WeChatError(RuntimeError):
    def __init__(self, code: int, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


# --------------------------------------------------------------------------- #
# 凭证
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_config(explicit_path: str | None, required: bool = True) -> dict:
    """优先级：命令行 --config > 环境变量 > 当前目录 config.json > ~/.config 下配置。"""
    cfg: dict = {}

    candidates = [Path.home() / ".config" / "wechat-mp-draft" / "config.json"]
    if explicit_path:
        candidates.insert(0, Path(explicit_path).expanduser())
    else:
        candidates.insert(0, Path.cwd() / "config.json")

    for p in candidates:
        if p.is_file():
            cfg.update(_read_json(p))
            cfg["_config_path"] = str(p)
            break

    if os.environ.get("WECHAT_MP_APPID"):
        cfg["appid"] = os.environ["WECHAT_MP_APPID"]
    if os.environ.get("WECHAT_MP_APPSECRET"):
        cfg["appsecret"] = os.environ["WECHAT_MP_APPSECRET"]

    if required and (not cfg.get("appid") or not cfg.get("appsecret")):
        sys.exit(
            "缺少凭证。请设置环境变量 WECHAT_MP_APPID / WECHAT_MP_APPSECRET，\n"
            "或参考 config.example.json 写一份 config.json（不要提交到 git）。"
        )
    return cfg


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _http(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        sys.exit(f"网络请求失败：{e.reason}（检查网络/代理）")

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(f"接口返回非 JSON：{raw[:300]}")

    if isinstance(result, dict) and result.get("errcode") not in (None, 0):
        raise WeChatError(int(result["errcode"]), str(result.get("errmsg", "")))
    return result


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """files: {field: (filename, bytes, content_type)}"""
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (filename, blob, ctype) in files.items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
            f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'
        ).encode()
        body += blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def egress_ip() -> str:
    """尽力查出本机公网出口 IP，查不到返回「未知」。"""
    for url in ("https://api.ipify.org", "https://ipv4.icanhazip.com", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=6) as r:
                ip = r.read().decode().strip()
            if ip:
                return ip
        except Exception:
            continue
    return "未知"


HINTS = {
    40164: "调用 IP 不在白名单。去微信开发者平台 → 我的业务 → 公众号 → 基础信息 → API IP白名单，把出口 IP 加进去再重试。",
    61004: "调用 IP 不在白名单（同上）。",
    89503: "该 IP 首次调用需要公众号管理员在微信里确认，确认后重试。",
    40001: "token 失效（AppSecret 被重置，或被其它程序刷新）。删掉本地 token 缓存后重跑即可。",
    42001: "token 过期。重跑一次会自动刷新。",
    40125: "AppSecret 不正确。",
    40243: "AppSecret 已被冻结，去开发者平台解冻。",
    48001: "该账号没有此接口权限。先查开发者平台「接口权限与额度」，再决定是否改走浏览器自动化。",
    45009: "当日调用额度用尽。",
    45011: "分钟级限频，稍等再试。",
    50004: "该账号禁止使用 token 接口。",
}


def hint_for(code: int) -> str:
    return HINTS.get(code, "")


def explain(err: WeChatError) -> None:
    hints = HINTS
    print(f"\n接口失败：{err}", file=sys.stderr)
    if err.code in (40164, 61004, 89503):
        print(f"当前出口 IP：{egress_ip()}", file=sys.stderr)
    if err.code in hints:
        print(f"建议：{hints[err.code]}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# token
# --------------------------------------------------------------------------- #
def get_token(cfg: dict, force: bool = False) -> str:
    appid = cfg["appid"]
    if not force:
        cached = _read_json(TOKEN_CACHE)
        if (
            cached.get("appid") == appid
            and cached.get("access_token")
            and float(cached.get("expires_at", 0)) > time.time()
        ):
            return cached["access_token"]

    payload = json.dumps(
        {"grant_type": "client_credential", "appid": appid, "secret": cfg["appsecret"]}
    ).encode()
    data = _http(
        f"{API_BASE}/cgi-bin/stable_token",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    token = data["access_token"]
    expires_in = int(data.get("expires_in", 7200))
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(
            json.dumps(
                {"appid": appid, "access_token": token, "expires_at": time.time() + expires_in - 300}
            ),
            encoding="utf-8",
        )
        TOKEN_CACHE.chmod(0o600)
    except Exception:
        pass  # 缓存失败不影响主流程
    return token


# --------------------------------------------------------------------------- #
# 内容处理
# --------------------------------------------------------------------------- #
def strip_tags(html: str) -> str:
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def guess_title(html: str, fallback: str) -> str:
    for tag in ("h1", "h2"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, flags=re.S | re.I)
        if m:
            t = strip_tags(m.group(1))
            if t:
                return t
    return fallback


def find_images(html: str) -> list[str]:
    return re.findall(r"<img\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", html, flags=re.I)


def prepare_image(path: Path) -> Path:
    """uploadimg 只收 jpg/png 且 < 1MB；超限时尝试用 macOS 自带 sips 压到临时文件。"""
    suffix = path.suffix.lower()
    ok_type = suffix in (".jpg", ".jpeg", ".png")
    ok_size = path.stat().st_size < MAX_IMG_BYTES
    if ok_type and ok_size:
        return path

    tmp_dir = Path("/tmp/wechat-mp-draft")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"{path.stem[:40]}-{abs(hash(path)) % 10**6}.jpg"
    try:
        subprocess.run(
            ["sips", "-Z", "1600", "-s", "format", "jpeg", "-s", "formatOptions", "80",
             str(path), "--out", str(out)],
            check=True, capture_output=True,
        )
    except Exception as exc:
        raise SystemExit(
            f"图片 {path.name} 不符合要求（需 jpg/png 且 <1MB），自动压缩失败：{exc}\n"
            "请手动压缩后重试。"
        )
    if out.stat().st_size >= MAX_IMG_BYTES:
        raise SystemExit(f"图片 {path.name} 压缩后仍超过 1MB，请手动处理。")
    print(f"  已压缩：{path.name} → {out.name}")
    return out


def upload_content_image(token: str, path: Path) -> str:
    blob = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    body, ct = _multipart({}, {"media": (path.name, blob, ctype)})
    data = _http(
        f"{API_BASE}/cgi-bin/media/uploadimg?access_token={urllib.parse.quote(token)}",
        data=body,
        headers={"Content-Type": ct},
        method="POST",
    )
    return data["url"]


def upload_cover(token: str, path: Path) -> str:
    """封面必须是永久素材 media_id。"""
    blob = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "image/png"
    body, ct = _multipart({}, {"media": (path.name, blob, ctype)})
    data = _http(
        f"{API_BASE}/cgi-bin/material/add_material?access_token={urllib.parse.quote(token)}&type=image",
        data=body,
        headers={"Content-Type": ct},
        method="POST",
    )
    return data["media_id"]


def inline_images(html: str, base_dir: Path, token: str) -> str:
    mapping: dict[str, str] = {}
    for src in find_images(html):
        if src in mapping:
            continue
        if src.startswith(("http://", "https://", "data:")):
            print(f"  ! 跳过外链图片（微信会过滤外部 URL）：{src[:80]}")
            continue
        local = (base_dir / src).resolve()
        if not local.is_file():
            print(f"  ! 图片不存在，跳过：{src}")
            continue
        print(f"  上传正文图片：{local.name}")
        mapping[src] = upload_content_image(token, prepare_image(local))

    for old, new in mapping.items():
        html = html.replace(f'"{old}"', f'"{new}"').replace(f"'{old}'", f"'{new}'")
    return html


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def do_check(cfg: dict) -> int:
    token = get_token(cfg, force=True)
    print("✓ access_token 获取成功（稳定版接口）")

    data = _http(f"{API_BASE}/cgi-bin/draft/count?access_token={urllib.parse.quote(token)}")
    print(f"✓ draft/count 调用成功，当前草稿总数：{data.get('total_count', data)}")
    print("\n结论：本账号可以调用草稿箱接口，路线 A 可用。")
    return 0


def list_drafts(token: str, offset: int, count: int = 20) -> list[dict]:
    """翻一页草稿列表（不带正文，省流量）。"""
    body = json.dumps({"offset": offset, "count": count, "no_content": 1}).encode("utf-8")
    data = _http(
        f"{API_BASE}/cgi-bin/draft/batchget?access_token={urllib.parse.quote(token)}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return data.get("item", []) or []


def find_draft_by_title(token: str, title: str, max_scan: int = 200) -> str | None:
    """按标题找已有草稿，返回 media_id；有多条同名时取最近更新的那条。"""
    offset = 0
    best: tuple[int, str] | None = None
    while offset < max_scan:
        items = list_drafts(token, offset)
        if not items:
            break
        for it in items:
            news = (it.get("content") or {}).get("news_item") or []
            if news and news[0].get("title") == title:
                ts = int(it.get("update_time") or 0)
                if best is None or ts > best[0]:
                    best = (ts, it.get("media_id", ""))
        if len(items) < 20:
            break
        offset += len(items)
    return best[1] if best else None


def update_draft(token: str, media_id: str, articles: list[dict]) -> dict:
    body = json.dumps({"media_id": media_id, "index": 0, "articles": articles}, ensure_ascii=False).encode("utf-8")
    return _http(
        f"{API_BASE}/cgi-bin/draft/update?access_token={urllib.parse.quote(token)}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def build_articles(args, cfg: dict, token: str | None, html: str, base_dir: Path) -> dict:
    title = args.title or guess_title(html, base_dir.name)
    author = args.author or cfg.get("author") or ""

    if len(title) > MAX_TITLE:
        sys.exit(f"标题 {len(title)} 字，超过 {MAX_TITLE} 字上限：{title}")
    if author and len(author) > MAX_AUTHOR:
        sys.exit(f"作者 {len(author)} 字，超过 {MAX_AUTHOR} 字上限。")

    digest = args.digest
    if digest and len(digest) > MAX_DIGEST:
        sys.exit(f"摘要 {len(digest)} 字，超过 {MAX_DIGEST} 字上限。")

    if token:
        html = inline_images(html, base_dir, token)

    if len(html) >= MAX_CONTENT_CHARS:
        sys.exit(f"正文 {len(html)} 字符，超过 20000 字符上限。请精简或拆分。")
    if len(html.encode()) >= MAX_CONTENT_BYTES:
        sys.exit("正文超过 1MB，请检查是否有内嵌图片。")

    cover_path = args.cover or cfg.get("default_cover")
    if not cover_path:
        sys.exit("缺少封面。请用 --cover 指定，或在 config.json 里设置 default_cover。")
    cover = Path(cover_path).expanduser()
    if not cover.is_file():
        sys.exit(f"封面文件不存在：{cover}")

    thumb_media_id = upload_cover(token, cover) if token else "<dry-run>"

    article = {
        "article_type": "news",
        "title": title,
        "author": author,
        "content": html,
        "thumb_media_id": thumb_media_id,
        "need_open_comment": 1,
        "only_fans_can_comment": 0,
    }
    if digest:
        article["digest"] = digest
    return {"articles": [article]}


def load_body(args) -> tuple[str, Path]:
    if args.html:
        p = Path(args.html).expanduser().resolve()
        if not p.is_file():
            sys.exit(f"找不到文件：{p}")
        return p.read_text(encoding="utf-8"), p.parent

    p = Path(args.md).expanduser().resolve()
    if not p.is_file():
        sys.exit(f"找不到文件：{p}")
    try:
        import markdown  # type: ignore
    except ImportError:
        sys.exit(
            "未安装 markdown 库（pip install markdown）。\n"
            "更推荐直接传你已经做好的行内样式 HTML：--html 文章.html"
        )
    return markdown.markdown(p.read_text(encoding="utf-8"), extensions=["tables", "fenced_code"]), p.parent


def main() -> int:
    ap = argparse.ArgumentParser(description="把文章写进微信公众号草稿箱（只写草稿，不发布）")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--html", help="行内样式 HTML 文件路径")
    src.add_argument("--md", help="Markdown 文件路径（需 pip install markdown）")
    ap.add_argument("--title", help="标题，≤32 字；缺省取 <h1> 或文件名")
    ap.add_argument("--author", help="作者，≤16 字")
    ap.add_argument("--digest", help="摘要，≤120 字；不填由微信自动截取")
    ap.add_argument("--cover", help="封面图路径（建议 2.35:1）")
    ap.add_argument("--config", help="配置文件路径")
    ap.add_argument("--check", action="store_true", help="只体检：取 token + 查草稿总数，不写任何内容")
    ap.add_argument("--dry-run", action="store_true", help="不联网，只解析与校验，打印计划")
    ap.add_argument(
        "--update",
        action="store_true",
        help="按标题查重：已有同名草稿则原地更新，没有才新建（默认直接新建）",
    )
    args = ap.parse_args()

    cfg = load_config(args.config, required=not args.dry_run)

    if args.check:
        try:
            return do_check(cfg)
        except WeChatError as e:
            explain(e)
            return 1

    if not (args.html or args.md):
        ap.error("需要 --html 或 --md，或用 --check 只做体检")

    html, base_dir = load_body(args)

    if args.dry_run:
        title = args.title or guess_title(html, base_dir.name)
        imgs = find_images(html)
        local_imgs = [i for i in imgs if not i.startswith(("http", "data:"))]
        print("== dry-run，不会写草稿 ==")
        print(f"标题：{title}（{len(title)} 字）")
        print(f"正文：{len(html)} 字符 / {len(html.encode())} 字节")
        print(f"图片：共 {len(imgs)} 张，其中本地 {len(local_imgs)} 张需上传")
        print(f"封面：{args.cover or cfg.get('default_cover') or '未指定'}")
        return 0

    try:
        token = get_token(cfg)
        payload = build_articles(args, cfg, token, html, base_dir)

        if args.update:
            existing = find_draft_by_title(token, payload["articles"][0]["title"])
            if existing:
                update_draft(token, existing, payload["articles"])
                print(f"\n✓ 已按标题命中已有草稿，原地更新。media_id = {existing}")
                print("去后台「内容与互动 → 草稿箱」核对，发布仍需人工操作。")
                print(json.dumps({"media_id": existing, "action": "updated"}, ensure_ascii=False))
                return 0
            print("（--update：没找到同名草稿，改为新建）")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        data = _http(
            f"{API_BASE}/cgi-bin/draft/add?access_token={urllib.parse.quote(token)}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    except WeChatError as e:
        explain(e)
        return 1

    media_id = data.get("media_id", "")
    print(f"\n✓ 草稿已写入。media_id = {media_id}")
    print("去后台「内容与互动 → 草稿箱」核对，发布仍需人工操作。")
    print(json.dumps({"media_id": media_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
