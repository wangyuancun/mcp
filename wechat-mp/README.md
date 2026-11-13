# wechat-mp

把写好的文章直接投进微信公众号**草稿箱**的最小 MCP 服务。只写草稿，永不发布。

> **与 skills 合集的关系**：本目录是实现本体（MCP 服务 + CLI + 投递逻辑）。另一个仓库 [skills](https://github.com/wangyuancun/skills) 里只有一个对应的薄壳技能 `wechat-draft-porter/`，负责「何时调用、参数怎么传」，源码不复制过去，避免两处漂移。
>
> **本目录可独立使用**：可以直接 clone 整个 `mcp` 仓库后只进 `wechat-mp/` 子目录，也可以只取这一个目录；下面的命令都在本目录内执行。

A minimal MCP server that pushes your article into the WeChat Official Account **draft box** over stdio JSON-RPC. Drafts only — it never publishes.

---

## 这是什么

一个不到 1,000 行、只用 Python 标准库的小服务，通过 MCP（Model Context Protocol）stdio 协议，把三件事暴露给你的 agent 客户端：

| 工具 | 做什么 |
|---|---|
| `draft_push` | 把一个 html 或 md 文件投递成草稿：取 token → 上传正文图片 → 上传封面永久素材 → 新建/更新草稿 |
| `check` | 体检：取 access_token、查草稿总数、打印当前出口 IP，用来排查白名单和凭证问题 |
| `list_drafts` | 列出最近的草稿标题，确认某篇是不是已经投过 |

## 解决什么问题

公众号后台的编辑器只能手工复制粘贴，一篇文章的标题、作者、摘要、正文样式、图片、封面要一个个重填。用官方接口可以一次性写进草稿箱，你在手机上只需要点「发表」。

**边界很清楚**：个人主体（未认证）账号已被回收「发布能力」接口，`freepublish/*` 全部无权限，所以**最后一步发表永远人工**。本仓库不尝试绕过这一点，也没有任何发布代码。

---

## 五步上手

### 1. 拿到代码

```bash
git clone https://github.com/wangyuancun/mcp.git
cd mcp/wechat-mp
```

不需要 `pip install`。唯一可选的依赖是 `markdown`（只在投 `.md` 时用到）：

```bash
pip install markdown
```

### 2. 填凭证

二选一。

**方式 A：环境变量**

```bash
export WECHAT_MP_APPID='wx0000000000000000'
export WECHAT_MP_APPSECRET='your_app_secret'
```

**方式 B：本地配置文件**（推荐，能设 600 权限）

```bash
cp config.example.json config.json
# 填入真实的 AppID / AppSecret
chmod 600 config.json
```

配置查找顺序：`./config.json` → `~/.config/wechat-mp-draft/config.json` → 环境变量覆盖。

### 3. 把出口 IP 加进白名单

见下一节「配置说明」。**不做这一步，任何接口调用都会返回 40164。**

### 4. 自检

```bash
python3 -m wxmp.api --check
```

预期输出：

```
✓ access_token 获取成功（稳定版接口）
✓ draft/count 调用成功，当前草稿总数：19

结论：本账号可以调用草稿箱接口，路线 A 可用。
```

失败会直接告诉你原因，并在 40164 时打印当前出口 IP。

### 5. 投第一条草稿

命令行：

```bash
python3 -m wxmp.api --html article.html --title "我的标题" --cover cover.jpg
```

或者接进 MCP 客户端（见下节），让 agent 调 `draft_push`。成功会返回 `media_id`，去后台草稿箱就能看到。

---

## 配置说明

### AppID / AppSecret 从哪拿

2025-12-01 起，公众号后台的「设置与开发 → 基本配置」已下线，统一迁到**微信开发者平台**：

> `developers.weixin.qq.com` → 我的业务 → 公众号 → 选择你的号 → **基础信息**

页面上能看到 AppID；AppSecret 默认不可见，只能点「重置」——重置会让旧 secret 立即失效，新值**只显示一次**，请当场存好。重置需要公众号管理员微信扫码授权。

### IP 白名单怎么加

同一页面的「**API IP白名单**」→ 编辑：

- **一行一个 IP**，不要用空格或逗号分隔，否则会提示「输入格式有误，可调整后再试。」且确定按钮置灰
- 保存需要**公众号管理员扫码二次授权**
- 白名单只对「获取 access_token」这一步强校验，但 token 来自白名单 IP，所以等价于整条链路都受约束

**家用宽带是动态 IP**，重拨就失效，表现为 40164。长期使用建议：放到固定出口的机器上跑，或者每次失败后按提示补一条。

### 为什么发布接口用不了

2025 年 7 月起，微信回收了个人主体账号的「发布能力」接口权限。开发者平台的「接口管理 → 接口权限与额度」里，「发布能力」分组下的 5 个接口（获取已发布消息列表、删除发布文章、发布状态查询、获取已发布图文信息、发布草稿）对个人号全部显示「无权限」。

同时「草稿管理」7 个接口、素材管理的上传接口都是「有权限」，所以**投草稿能自动化，发表必须人工**。

想确认自己账号的情况，去看那个页面，或调 `check` 工具后对照文档。

---

## 接进 MCP 客户端

服务用 stdio 通信，客户端配置里加一段即可（示例见 `mcp_config.example.json`）：

```json
{
  "mcpServers": {
    "wechat-mp": {
      "command": "python3",
      "args": ["-m", "wxmp"],
      "cwd": "/absolute/path/to/mcp/wechat-mp",
      "env": {
        "WECHAT_MP_APPID": "wx0000000000000000",
        "WECHAT_MP_APPSECRET": "your_app_secret"
      }
    }
  }
}
```

凭证建议写在 `config.json` 里而不是客户端配置里，客户端配置容易被同步/分享。仓库的 `.gitignore` 已排除 `config.json`。

### 工具参数

`draft_push`

| 参数 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | html 或 md 文件绝对路径 |
| `title` | 否 | ≤32 字；不填取 `<h1>`，再退到文件名 |
| `cover` | 否 | 封面图路径，建议 2.35:1（如 900×383）；不填读配置 `default_cover` |
| `author` | 否 | ≤16 字；不填读配置 |
| `digest` | 否 | ≤120 字；不填由微信自动截取 |
| `update_existing` | 否 | `true` 时先按标题查重，命中则原地更新，避免改稿堆出多条；默认 `false` |

`check`：无参数。

`list_drafts`：`limit`（默认 20，上限 50）。

---

## 踩坑记录

这些都是真实踩过的，按遇到顺序排：

1. **「设置与开发 → 基本配置」打不开了**。2025-12-01 起迁到微信开发者平台，旧地址直接 404。白名单、AppSecret、域名配置都在 `developers.weixin.qq.com` 的「我的业务 → 公众号 → 基础信息」。
2. **白名单不接受空格分隔**。用空格或逗号粘贴多个 IP 会报「输入格式有误，可调整后再试。」，确定按钮变灰。必须一行一个。
3. **保存白名单要管理员扫码**。弹窗「管理员扫码授权设置 API IP 白名单」，扫码前不落库，别提前关窗口。
4. **重置 AppSecret 要再扫一次码**。两次授权互相独立，不能一次扫完。新值只显示一次，页面原文：「AppSecret 已生成，平台将不再储存和显示，需妥善保存。」
5. **标题上限 32 字，不是后台显示的 64**。后台编辑器里标题计数写着 `0/64`，但 `draft/add` 接口按 32 字卡。按 UI 写会被拒。别指望脚本静默截断——本项目是直接报错退出，请手改。
6. **正文图片不能是外链**。微信会把 `<img src="https://你的域名/...">` 过滤掉。必须先把图片通过 `media/uploadimg` 上传，拿到 `mmbiz.qpic.cn` 的地址再塞回正文。本项目会自动做这一步（仅支持本地图片，jpg/png，<1MB）。
7. **封面必须是永久素材**。`thumb_media_id` 不能随手传个临时素材或外链，要走 `material/add_material?type=image` 上传。建议 900×383。
8. **个人主体没有发布权限**。`freepublish/*` 全部 48001 或无权限，只能写草稿，最后一步人工点发表。
9. **动态 IP 是最常见的偶发失败**。40164 不是代码问题，是出口 IP 变了。`check` 工具会把当前 IP 打出来。
10. **access_token 会被互踢**。多个程序同时取 token，旧的立刻失效。本项目统一走 `stable_token` 并在本地缓存，减少互相影响。

## 安全说明

- 仓库内不含任何真实 AppID、AppSecret、IP 地址、草稿 ID
- 凭证只从环境变量或本地配置文件读取，不写日志、不打印
- 代码中不存在 `freepublish` / 群发 / 定时发表相关调用
- 配置文件默认被 `.gitignore` 排除；建议 `chmod 600`

---

## English

`wechat-mp` is a tiny MCP server (stdlib only, stdio JSON-RPC) that pushes a local HTML/Markdown file into a WeChat Official Account **draft box**.

Tools: `draft_push` (file, title, cover, update_existing), `check` (credentials + draft count + egress IP), `list_drafts`.

Quick start:

```bash
cp config.example.json config.json   # fill appid/appsecret, chmod 600
export WECHAT_MP_APPID=... WECHAT_MP_APPSECRET=...   # or use config.json
python3 -m wxmp.api --check          # verify token + whitelist
python3 -m wxmp                      # start the stdio MCP server
```

Notes: your public egress IP must be added to the API IP whitelist (one IP per line; saving requires the account admin to scan a QR code). Personal/unverified accounts have no publishing permission — this project only creates drafts and never publishes.

## License

MIT
