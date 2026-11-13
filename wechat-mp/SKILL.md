---
name: "wechat-draft-porter"
display_name: "公众号草稿搬运工"
display_name_en: "WeChat Draft Porter"
description: "把 markdown 或行内样式 HTML 文章送进微信公众号草稿箱，只写草稿、绝不发布。当用户说「投草稿」「发到草稿箱」「把这篇文章传到公众号后台」「公众号排版稿入库」时使用。"
description_zh: "把本地 HTML 或 Markdown 文章写入微信公众号草稿箱，自动上传正文图片与封面。使用前需自备公众号 AppID 与 AppSecret，并把本机出口 IP 加入公众号后台的 IP 白名单。本技能只创建草稿，是否发布始终由作者本人在公众号后台点击确认。"
description_en: "Writes a local HTML or Markdown article into the WeChat Official Account draft box and uploads inline images and the cover automatically. You need your own AppID and AppSecret, and your egress IP must be whitelisted in the WeChat console. It only creates drafts; publishing is always confirmed manually."
version: "0.1.0"
tags:
  - wechat
  - official-account
  - publishing
  - draft
  - mcp
author: "wangyuancun"
license: "MIT"
examples_zh:
  - "帮我把 ~/Desktop/article.html 投到公众号草稿箱，标题用「我的标题」"
  - "先跑一次体检，看本机出口 IP 和草稿权限是否正常"
  - "更新已经投过的那篇草稿，不要新建一条"
examples_en:
  - "Push ~/Desktop/article.html to my WeChat Official Account draft box with the title 'My Post'"
  - "Run a health check to verify the egress IP and draft permission"
  - "Update the existing draft with the same title instead of creating a new one"
---

# 公众号草稿搬运工 (WeChat Draft Porter)

本目录是被 [skills 合集](https://github.com/wangyuancun/skills) 中薄壳技能 `wechat-draft-porter/` 引用的**实现本体**：一个 stdio MCP 服务，外加可直接调用的 CLI。位于 [mcp 合集](https://github.com/wangyuancun/mcp) 的 `wechat-mp/` 子目录，可独立使用。

## 何时调用

- 用户说「把这篇文章投到草稿箱」「发到公众号后台」「排版稿入库」
- 需要确认某篇是否已投过 → `list_drafts`
- 改稿后不想堆出多条草稿 → `draft_push` 带 `update_existing: true`
- ❌ 不要用于发布/群发/定时发表：个人主体账号没有发布接口权限

## 快速开始

```bash
cp config.example.json config.json   # 填 appid / appsecret
chmod 600 config.json
python3 -m wxmp.api --check          # 看到 ✓ draft/count 才算通
python3 -m wxmp                      # 启动 MCP 服务（stdio）
```

详细配置、白名单、踩坑记录见 [README.md](./README.md)。

## 工具

| 工具 | 说明 |
|---|---|
| `draft_push` | 参数 `file`（必填）、`title`、`cover`、`author`、`digest`、`update_existing` |
| `check` | 取 token、查草稿总数、打印出口 IP |
| `list_drafts` | 列最近草稿标题，`limit` 默认 20 |

## 约束

- 只写草稿，**绝不调用 `freepublish/*`**
- 标题 ≤ 32 字，超长直接报错，不静默截断
- 正文图片必须是本地文件（会 `media/uploadimg` 换成微信图床地址），封面走永久素材
- 凭证只从 `config.json` / 环境变量读取，不打印、不入库
