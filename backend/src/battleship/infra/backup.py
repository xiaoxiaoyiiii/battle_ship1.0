"""七天一次的 SQLite 在线快照；失败不影响对局，保留最近四份。"""
import asyncio
import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from .logging import get_logger

logger=get_logger('backup')


class DatabaseBackup:
    def __init__(self,source:Path,directory:Path):
        self.source=Path(source).resolve()
        self.directory=Path(directory).resolve()

    def run_due(self,*,now=None):
        now=int(time.time()) if now is None else int(now)
        temporary=None
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            existing=sorted(self.directory.glob('weekly-*.db'))
            if existing and now-int(existing[-1].stem.split('-')[1])<7*86400:
                return False
            if not self.source.is_file():
                raise FileNotFoundError('备份源库不存在')
            filename=f'weekly-{now:012d}-{uuid.uuid4().hex[:8]}.db'
            destination=self.directory/filename
            temporary=destination.with_suffix('.partial')
            with closing(sqlite3.connect(self.source.as_uri()+'?mode=ro',uri=True)) as source:
                with closing(sqlite3.connect(temporary)) as target:
                    source.backup(target)
                    if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                        raise RuntimeError('备份完整性检查失败')
            temporary.replace(destination)
            for old in sorted(self.directory.glob('weekly-*.db'))[:-4]:
                old.unlink()
            logger.info('每周数据库快照完成',extra={'backup_path':str(destination)})
            return True
        except Exception:
            logger.exception('每周数据库备份失败')
            return False
        finally:
            if temporary and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    logger.exception('备份临时文件清理失败')


class Maintenance:
    def __init__(self,database,ranked_seasons,backup_directory=None):
        self.seasons=ranked_seasons
        self.backup=DatabaseBackup(database.path,backup_directory or database.path.parent/'backups') if database.path else None
        self.task=None
        self.stopped=asyncio.Event()

    async def _run(self):
        while not self.stopped.is_set():
            try:
                await asyncio.to_thread(self.seasons.current)
                if self.backup:
                    await asyncio.to_thread(self.backup.run_due)
            except Exception:
                logger.exception('赛季维护任务失败，将在下一轮重试')
            try:
                await asyncio.wait_for(self.stopped.wait(),timeout=30)
            except TimeoutError:
                pass

    def start(self):
        self.stopped.clear()
        self.task=asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.stopped.set()
            await self.task
            self.task=None
