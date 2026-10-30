"""Where the runtime assets live after the migration window closed.

Phase 5 deleted the old panel (templates + static CSS/JS), so only two things
remain outside the built frontend:

* **user data** — uploaded avatars under `static/avatars`, kept on the same
  frozen `/static/avatars/...` URLs so existing profiles keep working;
* **the Vite build output** — `frontend/dist` (content-hashed assets + manifest),
  mounted by `http/routers/frontend.py`.

Repository-root discovery only looks for the new layout (backend package +
frontend directory); the deleted panel left no marker behind.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "backend" / "src" / "battleship").is_dir() and (path / "frontend").is_dir()


@dataclass(frozen=True)
class AssetPaths:
    root: Path
    avatars_dir: Path
    frontend_dist: Path

    @classmethod
    def discover(cls, root: str | Path | None = None) -> "AssetPaths":
        candidates: list[Path] = []
        if root is not None:
            candidates.append(Path(root))
        env_root = os.environ.get("BATTLESHIP_ROOT")
        if env_root:
            candidates.append(Path(env_root))

        here = Path(__file__).resolve()
        candidates.extend(here.parents)
        candidates.append(Path.cwd())

        for candidate in candidates:
            resolved = candidate.resolve()
            if _looks_like_repo_root(resolved):
                return cls._at(resolved)

        # 没有仓库根时退回当前目录：服务仍能启动，健康检查/前端挂载会指出缺失。
        return cls._at(Path.cwd().resolve())

    @classmethod
    def _at(cls, root: Path) -> "AssetPaths":
        return cls(
            root=root,
            avatars_dir=root / "static" / "avatars",
            frontend_dist=root / "frontend" / "dist",
        )


__all__ = ["AssetPaths"]
