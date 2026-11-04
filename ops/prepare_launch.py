"""在停服或隔离库中准备已批准的开服赛季与唯一管理员外观。"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'backend/src'), str(ROOT)]


def resolve_start(config, starts_at=None):
    """切换时显式传入实际开服时间，避免预演或重跑悄悄打开赛季。"""
    value = starts_at if starts_at is not None else config.get('starts_at')
    if type(value) is not int or value <= 0:
        raise ValueError('本季按实际开服时刻起算，须用 --starts-at 显式指定 Unix 秒')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--config', default=str(ROOT/'ops/launch-20261104.json'))
    parser.add_argument('--admin-user-id', required=True)
    parser.add_argument('--starts-at', type=int, help='实际开服时刻的 Unix 秒；只用于首次预置，不覆盖已有季')
    parser.add_argument('--service', default='battleship')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if args.dry_run:
        print(json.dumps({'database':str(Path(args.database).resolve()),'season':config,'writes':False},ensure_ascii=False))
        return 0
    starts_at = resolve_start(config, args.starts_at)
    if not args.offline:
        from ops.service_state import require_stopped
        require_stopped(args.service)
    from battleship.repositories import Database
    from battleship.repositories.migrations import backup_database, verify_database
    from battleship.services.battle_pass import BattlePassService
    from battleship.services.auth import AuthService
    from battleship.config import Settings
    path = Path(args.database).resolve()
    problems = verify_database(path)
    if problems:
        raise ValueError('须先迁移并核验数据库：'+'; '.join(problems))
    database = Database.from_path(path)
    try:
        with database.unit_of_work() as uow:
            if uow.users.get(args.admin_user_id) is None:
                raise ValueError('指定的云端管理员账号不存在，不创建替代账号')
        backup = backup_database(path)
        season = BattlePassService(database).seed_default(config['season_id'], starts_at)
        auth = AuthService(database, Settings(secret_key='仅用于离线权限配置，不用于运行服务',
                            debug_admin_user_ids_raw=args.admin_user_id))
        auth.provision_admin_cosmetics()
        print(json.dumps({'ok':True,'backup':str(backup),'season':season,'admin_cosmetics':'已按唯一账号幂等配置'},ensure_ascii=False))
    finally:
        database.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
