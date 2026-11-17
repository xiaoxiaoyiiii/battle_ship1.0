"""电脑科技决策只消费本人选项和服务端已授权的合法目标。"""
from ..mystery_tech.catalog import BY_ID


def choose_technology(options, rng):
    ranks = {'quality': 1, 'legendary': 2, 'mythic': 3}
    best = max(ranks[BY_ID[option['tech_id']].tier] for option in options)
    return rng.choice([option['tech_id'] for option in options
                       if ranks[BY_ID[option['tech_id']].tier] == best])


def target_payload(request, rng):
    """复活时检查整艘船；找不到合法落点时返回None跳过，不等待超时。"""
    payload = {'request_id': request['request_id']}
    if request['kind'] == 'revive':
        allowed = {(cell['x'], cell['y']) for cell in request['legal_cells']}
        candidates = []
        for ship in request['ships']:
            origin = ship['positions'][0]
            for x, y in sorted(allowed):
                if all((x + pos['x'] - origin['x'], y + pos['y'] - origin['y']) in allowed
                       for pos in ship['positions']):
                    candidates.append({'ship_index': ship['ship_index'], 'x': x, 'y': y})
        return {**payload, **rng.choice(candidates)} if candidates else None
    if request['ship_indices']:
        payload['ship_index'] = rng.choice(request['ship_indices'])
    if request['legal_cells']:
        payload.update(rng.choice(request['legal_cells']))
    return payload
