"""在操作生产数据库前，确认 systemd 服务已经停止。"""

from __future__ import annotations

import os
import subprocess


class ServiceStateError(RuntimeError):
    """无法确认服务已停止，调用方必须中止数据库操作。"""


def require_stopped(service: str, *, start_pre: bool = False) -> None:
    try:
        result = subprocess.run(
            ["systemctl", "show", service, "--property=LoadState,ActiveState,SubState,MainPID,ControlPID"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as error:
        raise ServiceStateError(f"无法检查服务 {service}: {error}") from error
    if result.returncode != 0:
        raise ServiceStateError(f"无法检查服务 {service}: {result.stderr.strip()}")
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    stopped = state.get("ActiveState") in {"inactive", "failed"}
    # ExecStartPre 自身是 ControlPID；只允许本次启动前迁移进入，拒绝并行的手动迁移。
    own_start_pre = (
        start_pre and state.get("ActiveState") == "activating"
        and state.get("SubState") == "start-pre"
        and state.get("ControlPID") == str(os.getpid())
    )
    if state.get("LoadState") != "loaded" or state.get("MainPID") != "0" or not (stopped or own_start_pre):
        raise ServiceStateError(
            f"服务 {service} 尚未停止或状态不明 "
            f"(state={state.get('ActiveState')}, pid={state.get('MainPID')})"
        )
