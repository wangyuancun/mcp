"""python -m wxmp  →  启动 stdio MCP 服务。"""
from .server import main

if __name__ == "__main__":
    raise SystemExit(main())
