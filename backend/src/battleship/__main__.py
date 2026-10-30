"""`python -m battleship`：读取配置并以 uvicorn 启动组合应用。"""

from __future__ import annotations

import sys


def main() -> int:
    from .config import ConfigError, load_settings

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"启动失败: {exc}", file=sys.stderr)
        return 2

    import uvicorn

    # 用字符串目标交给 uvicorn 导入，避免 `__main__` 与 `battleship.main`
    # 各建一份应用（旧栈"模块名是 __main__"那类双实例坑）。
    uvicorn.run(
        "battleship.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())