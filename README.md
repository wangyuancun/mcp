# MCP Servers

个人收集的 MCP（Model Context Protocol）server 合集。每个 server 一个子目录，可以单独 clone 使用，也可以整体 clone 后只进某一个子目录。

## 收录

| Server | 一句话 | 传输方式 |
| :--- | :--- | :--- |
| **[wechat-mp](./wechat-mp/)** | 把 markdown / 行内样式 HTML 文章投进微信公众号草稿箱，只写草稿不发布。 | stdio |

## 安装与配置通则

1. **进子目录**：每个 server 的依赖、配置、入口都在自己目录里，命令一律在子目录内执行。

```bash
git clone https://github.com/wangyuancun/mcp.git
cd mcp/wechat-mp
```

2. **看该目录的 README**：安装步骤、凭证从哪拿、需要什么前置条件，都由各 server 自己说明。
3. **凭证走本地文件或环境变量**：一般 `cp config.example.json config.json` 后填值，并 `chmod 600`。仓库里的示例文件只含占位值。
4. **接进客户端**：多数 server 用 `python3` 起进程，客户端配置片段见各自目录的 `mcp_config.example.json`。`command` + `args` + `cwd` 三项要对准子目录。
5. **自检再使用**：能体检的 server 都提供一个不产生副作用的自检命令（如 `python3 -m wxmp.api --check`），先跑通再接客户端。

## 合集约定

1. **每个 server 一个顶层子目录**，目录名用短横线小写（如 `wechat-mp`），与该 server 的包名/技能名对应。
2. **子目录自包含**：自己的 `pyproject.toml`、`README.md`、入口文件、示例配置、`.gitignore`、`LICENSE`。不跨子目录引用代码。
3. **同一个 server 不在别处再存一份源码**。需要分发技能定义的，在别的仓库放薄壳并指向本仓库的子路径，避免两处漂移。
4. **不得提交凭证**：AppSecret、token、Cookie、真实 AppID、真实 IP、草稿 ID 一律不入库；示例值只用占位（`wx0000000000000000`）。
5. **默认最小依赖**：优先标准库；需要第三方依赖时写进该目录的 `pyproject.toml`。
6. **新增 server 时同步更新本文件的表格**，一行一个链接 + 一句话。
