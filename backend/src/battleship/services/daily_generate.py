"""从真实引擎模拟大师败局生成私有残局，不接触用户数据库。

python -m battleship.services.daily_generate --out <私有目录> --start-date 2026-11-03 --matches 128
每个进程独占随机源；原始对局、完整快照及验证轨迹只能写在静态目录和Git之外。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from ..domain.daily_challenge import restore_snapshot, snapshot_hash
from .daily_simulation import qualify, run_trial


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def accepted(quality: dict) -> bool:
    trials = quality.get('random_trials', 0)
    return bool(quality.get('solved') and trials >= 50 and quality.get('unresolved', 0) == 0
                and 0 <= quality.get('random_wins', trials) / trials <= .1
                and quality.get('winning_path', {}).get('actions'))


def publish(candidates: list[dict], out: Path, start_date: str) -> list[dict]:
    """同一模拟源只取一关；自动通过与人工审核分别记录。"""
    entries, seen = [], set()
    start = date.fromisoformat(start_date)
    for candidate in candidates:
        seed, raw, quality = candidate['seed'], candidate['snapshot'], candidate['quality']
        if seed in seen or not accepted(quality) or len(entries) >= 7:
            continue
        restore_snapshot(raw, room_id='publish', user_id='human', name='校验', sid='offline')
        digest = snapshot_hash(raw)
        puzzle_id = f'sim-master-{seed:05d}-{candidate["point"]}'
        filename = f'{puzzle_id}.json'
        write_json(out / filename, raw)
        write_json(out / f'{puzzle_id}-proof.json', quality)
        summary = {k:v for k,v in quality.items() if k != 'winning_path'}
        entries.append({'puzzle_id':puzzle_id, 'date':(start+timedelta(days=len(entries))).isoformat(),
                        'name':candidate.get('name', f'逆风战术 {len(entries)+1}'),
                        'snapshot':filename, 'sha256':digest, 'reviewed':False, 'quality':summary,
                        'source':{'simulated':True,'seed':seed,'point':candidate['point'],
                                  'ai_difficulty':'master','proof':f'{puzzle_id}-proof.json'}})
        seen.add(seed)
    # 热更时只在完整清单写好后替换入口。
    temporary = out / 'daily_puzzles.pending.json'
    write_json(temporary, {'daily_puzzles':entries})
    temporary.replace(out / 'daily_puzzles.json')
    return entries


async def inspect_source(seed: int, out: Path, search_seeds: int) -> dict:
    result = await run_trial(None, seed)
    write_json(out / 'sources' / f'seed-{seed:05d}.json', result)
    report = {'seed':seed, 'terminal':result.get('terminal', False),
              'master_won':bool(result.get('terminal') and not result.get('won')),
              'points':len(result.get('snapshots', [])), 'checked':[]}
    if not report['master_won']:
        report['reason'] = result.get('reason', '模拟人类获胜，不属于败局源')
        return report
    # 越接近终局越优先，仍只使用真实记录的原始局面，不改牌堆或船位。
    points = result.get('snapshots', [])
    for index in reversed(range(len(points))):
        raw = points[index]['snapshot']
        quality = await qualify(raw, search_seeds=search_seeds, reject_early=True)
        write_json(out / 'quality' / f'seed-{seed:05d}-point-{index}.json', quality)
        report['checked'].append({'point':index, **{k:v for k,v in quality.items() if k != 'winning_path'}})
        if accepted(quality):
            room = restore_snapshot(raw, room_id='summary', user_id='human', name='模拟舰长', sid='offline')
            report['candidate'] = {'seed':seed,'point':index,'snapshot':raw,'quality':quality,
                'summary':{'round':room.round,'phase':room.current_phase.value,
                           'ships':[p.remaining_ships for p in room.players.values()],
                           'human_hand':[c.name for c in room.players['human'].magic_hand]}}
            break
    return report


def worker(seed: int, out: str, search_seeds: int) -> dict:
    report = asyncio.run(inspect_source(seed, Path(out), search_seeds))
    write_json(Path(out) / 'reports' / f'seed-{seed:05d}.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--start-date', required=True, help='首个生效日，连续7天')
    parser.add_argument('--matches', type=int, default=128)
    parser.add_argument('--seed-start', type=int, default=0)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--search-seeds', type=int, default=8)
    args = parser.parse_args()
    date.fromisoformat(args.start_date)
    if not (args.matches > 0 and 1 <= args.workers <= 8 and args.search_seeds > 0):
        parser.error('局数/搜索种子须为正数，并发进程1～8')
    out = Path(args.out).resolve()
    if (out / 'candidate-report.json').exists():
        parser.error('请使用新的输出目录，保留每批独立验证证据')
    candidates, reports = [], []
    source_dir = Path(__file__).resolve().parents[1]
    fingerprint = hashlib.sha256()
    for path in sorted(source_dir.rglob('*.py')):
        fingerprint.update(str(path.relative_to(source_dir)).encode())
        fingerprint.update(path.read_bytes())
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # 分批投递，已有7个不同来源合格后不再创建新对局。
        for batch in range(args.seed_start, args.seed_start+args.matches, args.workers):
            jobs = [pool.submit(worker, seed, str(out), args.search_seeds)
                    for seed in range(batch, min(batch+args.workers,args.seed_start+args.matches))]
            for future in as_completed(jobs):
                report = future.result()
                reports.append({k:v for k,v in report.items() if k != 'candidate'})
                if report.get('candidate'):
                    candidates.append(report['candidate'])
                print(json.dumps({'seed':report['seed'],'master_won':report['master_won'],
                    'points':report['points'],'accepted':len(candidates),'reason':report.get('reason')}, ensure_ascii=False), flush=True)
            if len(candidates) >= 7:
                break
    candidates.sort(key=lambda c:c['seed'])
    entries = publish(candidates, out / 'release', args.start_date)
    write_json(out / 'candidate-report.json', {'source_kind':'真实引擎模拟大师对局',
        'engine_fingerprint':fingerprint.hexdigest(), 'matches':len(reports),
        'master_wins':sum(r['master_won'] for r in reports),
        'restorable_points':sum(r['points'] for r in reports if r['master_won']),
        'published':len(entries),'missing':7-len(entries),
        'human_review':'待用户盲玩；全部 reviewed=false','sources':reports})
    print(json.dumps({'published':len(entries),'missing':7-len(entries),'manifest':str(out/'release'/'daily_puzzles.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
