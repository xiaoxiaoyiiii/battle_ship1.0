"""生产发布前的只读配置检查；可选地制作并验证 SQLite 一致性备份。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infrastructure.sqlite_maintenance import (  # noqa: E402
    backup_database, configured_database_path, database_ready, integrity_check,
    validate_migration_copy,
)


def configuration_errors(env: dict[str, str]) -> list[str]:
    errors = []
    if len(env.get('SECRET_KEY', '')) < 32:
        errors.append('SECRET_KEY 至少需要 32 个字符')
    if env.get('FLASK_DEBUG') == '1':
        errors.append('FLASK_DEBUG 必须关闭')
    if env.get('ENABLE_TEST_EVENTS') == '1':
        errors.append('ENABLE_TEST_EVENTS 必须关闭')
    origins = [s.strip() for s in env.get('CORS_ORIGINS', '').split(',') if s.strip()]
    if not origins:
        errors.append('必须显式设置 CORS_ORIGINS')
    for origin in origins:
        parsed = urlsplit(origin)
        if (origin == '*' or parsed.scheme not in ('http', 'https') or
                not parsed.netloc or parsed.path not in ('', '/') or
                parsed.query or parsed.fragment):
            errors.append(f'CORS_ORIGINS 含无效来源: {origin}')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=configured_database_path())
    parser.add_argument('--backup-to', type=Path, help='创建一致性备份；目标必须不存在')
    parser.add_argument('--migration-copy', type=Path, help='在另一份副本验证当前迁移')
    args = parser.parse_args()

    errors = configuration_errors(dict(os.environ))
    if not database_ready(args.db):
        errors.append(f'数据库未就绪: {args.db}')
    else:
        try:
            integrity_check(args.db)
        except Exception as exc:
            errors.append(f'数据库完整性检查失败: {exc}')
    if errors:
        for error in errors:
            print(f'失败: {error}', file=sys.stderr)
        return 1

    try:
        if args.backup_to:
            backup_database(args.db, args.backup_to)
            print(f'已备份并验证: {args.backup_to}')
        if args.migration_copy:
            validate_migration_copy(args.db, args.migration_copy)
            print(f'迁移副本已验证: {args.migration_copy}')
    except Exception as exc:
        print(f'备份或迁移副本失败: {exc}', file=sys.stderr)
        return 1
    print('发布前检查通过')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
