"""运行配置：沿用旧栈的环境变量名，缺失关键项时启动即失败。

为什么关键项没有默认值：旧栈 `SECRET_KEY` 缺失时会退化成一次性随机值
（重启后所有会话失效、多进程之间互相不认），属于"能启动但带着错误配置运行"。
spec 明确要求 fail-fast，所以这里把 `SECRET_KEY` 列为必需项，并在异常里
点名到底是哪个环境变量缺失/为空。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 必需环境变量（没有安全默认值）。报错时按这些名字提示。
REQUIRED_ENV_VARS: tuple[str, ...] = ("SECRET_KEY",)

# 字段名 -> 环境变量名，用于把 Pydantic 的校验错误翻译成部署者看得懂的名字。
ENV_NAME_BY_FIELD: dict[str, str] = {
    "host": "HOST",
    "port": "PORT",
    "secret_key": "SECRET_KEY",
    "database_path": "BATTLESHIP_DB_PATH",
    "turn_timeout_seconds": "TURN_TIMEOUT_SECONDS",
    "chain_display_delay_seconds": "CHAIN_DISPLAY_DELAY_SECONDS",
    "enable_test_events": "ENABLE_TEST_EVENTS",
    "seed": "BS_SEED",
    "frontend_mode": "FRONTEND_MODE",
    "frontend_dist": "FRONTEND_DIST",
    "cors_origins_raw": "CORS_ORIGINS",
    "debug_admin_user_ids_raw": "DEBUG_ADMIN_USER_IDS",
    "log_level": "LOG_LEVEL",
    "log_json": "LOG_JSON",
}

DEFAULT_CORS_ORIGINS = "http://localhost:5000,http://127.0.0.1:5000"


class ConfigError(RuntimeError):
    """配置缺失或非法。消息里必须点名环境变量，启动脚本据此直接退出。"""


class Settings(BaseSettings):
    """进程级配置。字段默认值 = 旧栈默认值（除 SECRET_KEY 外）。"""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        validate_default=True,
        populate_by_name=True,
    )

    host: str = "0.0.0.0"
    port: int = Field(default=5000, ge=1, le=65535)

    # 会话签名密钥。没有默认值；缺失即启动失败。
    secret_key: SecretStr = Field(...)

    database_path: Path = Path("./battleship.db")
    turn_timeout_seconds: int = Field(default=90, ge=0)
    chain_display_delay_seconds: float = Field(default=1.2, ge=0)
    enable_test_events: bool = False
    # Fixed RNG seed for contract replays / headless simulation (legacy BS_SEED).
    # None keeps the normal random source.
    seed: int | None = None

    # Phase 5：旧模板已删除，只有 Vue 壳这一种前端。这里仍识别 FRONTEND_MODE，
    # 但只接受 "spa"——旧的部署配置若还写着 legacy，启动即失败（D30 fail-fast），
    # 而不是静默 serving 一个不存在的页面。
    frontend_mode: str = Field(default="spa", validation_alias="FRONTEND_MODE")
    frontend_dist: Path | None = Field(default=None, validation_alias="FRONTEND_DIST")

    # 环境变量是逗号分隔字符串；对外暴露解析后的列表/集合。
    cors_origins_raw: str = Field(default=DEFAULT_CORS_ORIGINS, validation_alias="CORS_ORIGINS")
    debug_admin_user_ids_raw: str = Field(default="", validation_alias="DEBUG_ADMIN_USER_IDS")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    log_json: bool = Field(default=True, validation_alias="LOG_JSON")

    @field_validator("secret_key")
    @classmethod
    def _non_empty_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("SECRET_KEY 不能为空")
        return value

    @field_validator("frontend_mode")
    @classmethod
    def _known_frontend_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode != "spa":
            raise ValueError(
                f"FRONTEND_MODE={value!r} 已不可用：Phase 5 移除了 legacy 前端，"
                "请删除该环境变量（默认即 spa）"
            )
        return mode

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL 非法: {value!r}")
        return level

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    @property
    def cors_origins_explicitly_empty(self) -> bool:
        return not self.cors_origins

    @property
    def debug_admin_user_ids(self) -> set[str]:
        return {item.strip() for item in self.debug_admin_user_ids_raw.split(",") if item.strip()}

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


def _env_present(name: str, environ: Mapping[str, str]) -> bool:
    return bool((environ.get(name) or "").strip())


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """读取环境变量并校验。

    显式点名缺失/为空的环境变量，避免部署者只看到一句 Pydantic traceback。
    """
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_ENV_VARS if not _env_present(name, env)]
    if missing:
        raise ConfigError(
            "缺少或为空的环境变量: "
            + ", ".join(missing)
            + "（例如 SECRET_KEY=请填入随机长字符串；参考 backend/.env.example）"
        )

    kwargs = {
        field: env[env_name]
        for field, env_name in ENV_NAME_BY_FIELD.items()
        if env_name in env
    }
    try:
        return Settings(_env_file=None, **kwargs)
    except Exception as exc:  # pydantic.ValidationError 及少量解析错误
        raise ConfigError(_translate_validation_error(exc)) from exc


def _translate_validation_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            items = errors()
        except Exception:
            items = []
        if items:
            parts: list[str] = []
            for item in items:
                loc = item.get("loc") or ()
                field = str(loc[0]) if loc else ""
                env_name = ENV_NAME_BY_FIELD.get(field, field.upper())
                msg = item.get("msg", "非法值")
                parts.append(f"{env_name}: {msg}")
            return "环境变量校验失败: " + "; ".join(parts)

    # 兜底：把消息里出现的字段名换成环境变量名。
    message = str(exc)
    for field, env_name in ENV_NAME_BY_FIELD.items():
        message = message.replace(field, env_name)
    return f"环境变量校验失败: {message}"
