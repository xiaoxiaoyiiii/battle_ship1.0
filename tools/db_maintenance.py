"""离线数据库演练工具；目标必须是新路径。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infrastructure.sqlite_maintenance import backup_database, integrity_check, validate_migration_copy


def main(argv=None):
    parser = argparse.ArgumentParser(description='SQLite 一致性备份与副本迁移检查')
    parser.add_argument('action', choices=('check', 'backup', 'validate-copy'))
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    args = parser.parse_args(argv)
    if args.action == 'check':
        print(integrity_check(args.source))
        return 0
    if args.destination is None:
        parser.error('backup 与 validate-copy 需要 destination')
    if args.destination.exists():
        parser.error('destination 已存在，请使用新路径保存本次快照')
    op = backup_database if args.action == 'backup' else validate_migration_copy
    print(op(args.source, args.destination))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
