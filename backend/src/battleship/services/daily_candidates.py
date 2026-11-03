"""私有候选管道：只读用户库，完整快照才可出池；报告与关卡不进Git。

python -m battleship.services.daily_candidates --db <preview.db> --out <私有目录> --week 2026-11-02
加 --verify 才运行真人策略搜索和至少50局随机合法模拟；没有合格样本时输出空目录。
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from ..domain.daily_challenge import restore_snapshot, snapshot_hash
from ..repositories import Database


def audit(database: Database) -> tuple[dict, list[dict]]:
    report = {'matches': 0, 'ai_human_losses': 0, 'confirmed_master_losses': 0,
              'difficulty_unknown_losses': 0, 'restorable_action_points': 0,
              'candidate_count': 0, 'filtered': {}, 'sources': []}
    reasons = Counter()
    candidates = []
    with database.unit_of_work() as uow:
        sources = {row.match_id: row for row in uow.daily_challenges.sources()}
        for match, replay in uow.daily_challenges.historical_replays():
            report['matches'] += 1
            if (match.mode != 'ai' or not str(match.winner_id).startswith('ai-')
                    or str(match.loser_id).startswith('ai-') or not uow.users.get(match.loser_id)):
                reasons['非AI胜且注册人类败'] += 1
                continue
            report['ai_human_losses'] += 1
            source = sources.get(match.id)
            if source is None:
                old = json.loads(replay.replay) if replay else {}
                # 只有大师执行器会生成此前缀的system日志；普通聊天不能作为难度证据。
                master_log = any(s.get('kind') == 'system' and s.get('text', '').startswith('大师 AI 出牌被拒（')
                                 for s in old.get('steps', []))
                if master_log:
                    report['confirmed_master_losses'] += 1
                else:
                    report['difficulty_unknown_losses'] += 1
                reasons['旧录像缺完整牌堆和引擎态，不能还原行动点'] += 1
                continue
            report['confirmed_master_losses'] += 1
            points = json.loads(source.snapshots)[-5:]
            good = []
            for point in points:
                try:
                    raw = point['snapshot']
                    if snapshot_hash(raw) != point['sha256']:
                        raise ValueError('摘要不匹配')
                    room = restore_snapshot(raw, room_id='candidate', user_id='human', name='候选', sid='offline')
                    good.append({**point, 'match_id': match.id, 'source_user_id': source.user_id,
                                 'summary': {'round': room.round, 'phase': room.current_phase.value,
                                  'ships': [p.remaining_ships for p in room.players.values()],
                                  'hand_counts': [len(p.magic_hand) for p in room.players.values()]}})
                except (ValueError, KeyError, TypeError) as error:
                    reasons[f'行动点不可还原:{type(error).__name__}'] += 1
            report['restorable_action_points'] += len(good)
            candidates.extend(good)
    report['filtered'] = dict(reasons)
    report['candidate_count'] = len(candidates)
    return report, candidates


async def export_candidates(database, out: Path, week: str, *, verify: bool = False):
    report, candidates = audit(database)
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    selected_sources = set()
    from .daily_simulation import qualify
    for i, candidate in enumerate(candidates):
        source_key = (candidate['source_user_id'], candidate['match_id'])
        if source_key in selected_sources or len(entries) >= 7:
            continue
        raw = candidate.pop('snapshot')
        candidate['quality'] = await qualify(raw) if verify else {'status': '待运行质量门槛'}
        report['sources'].append(candidate)
        quality = candidate['quality']
        if not (quality.get('solved') and quality.get('random_trials', 0) >= 50
                and quality.get('random_wins', 51) / quality['random_trials'] <= .1):
            report['filtered']['尚未通过可解或随机通关门槛'] = report['filtered'].get('尚未通过可解或随机通关门槛', 0) + 1
            continue
        puzzle_id = f"tactic-{candidate['match_id'][:8]}-{i}"
        filename = f'{puzzle_id}.json'
        (out / filename).write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
        entries.append({'puzzle_id': puzzle_id, 'date': (date.fromisoformat(week)+timedelta(days=len(entries))).isoformat(),
                        'name': f'逆风残局 {len(entries)+1}', 'snapshot': filename,
                        'sha256': candidate['sha256'], 'reviewed': False, 'quality': quality})
        selected_sources.add(source_key)
    report['published_candidates'] = len(entries)
    report['missing_days'] = 7-len(entries)
    report['human_review'] = '待用户人工微调、盲玩过审；没有伪造历史缺失状态'
    (out/'candidate-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out/'daily_puzzles.json').write_text(json.dumps({'daily_puzzles':entries}, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--week', required=True, help='首个生效周一，YYYY-MM-DD')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    if date.fromisoformat(args.week).weekday() != 0:
        parser.error('--week 必须是周一')
    path = Path(args.db).resolve()
    if not path.is_file():
        parser.error('用户库不存在，禁止新建空库冒充样本')
    # SQLite URI 强制只读，既不迁移也不创建/改写用户源库。
    db = Database(f'sqlite:///file:{quote(path.as_posix(), safe=":/")}?mode=ro&uri=true')
    try:
        report = asyncio.run(export_candidates(db, Path(args.out), args.week, verify=args.verify))
        print(json.dumps({k:v for k,v in report.items() if k != 'sources'}, ensure_ascii=False, indent=2))
    finally:
        db.dispose()


if __name__ == '__main__':
    main()
