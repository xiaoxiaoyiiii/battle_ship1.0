const skills = {
  firepower_control: {
    name: '火力统制', commanderId: 'chichao', primary: '#ec5b58', accent: '#ffd2b8', surface: '#2a1924',
    path: 'M32 5v9m0 36v9M8 18l8 5m32 18 8 5M8 46l8-5m32-18 8-5M46 32a14 14 0 1 1-28 0 14 14 0 1 1 28 0ZM32 25v14m-7-7h14',
  },
  delayed_lock: {
    name: '延迟锁定', commanderId: 'qingtong', primary: '#58bad9', accent: '#c9f3ff', surface: '#122d39',
    path: 'M7 37a25 25 0 1 1 29 19M14 35a18 18 0 1 1 23 14M22 33a10 10 0 1 1 13 9m-3-10 17-17M32 29a3 3 0 1 1 0 6 3 3 0 0 1 0-6ZM12 43v10h10m32-10v10H44',
  },
  dauntless_fleet: {
    name: '无畏舰队', commanderId: 'tieanchor', primary: '#6091ff', accent: '#d3e4ff', surface: '#172841',
    path: 'M32 5 53 14v17c0 14-11 22-21 28-10-6-21-14-21-28V14L32 5ZM32 28v20m-7-14h14M20 38a12 10 0 0 0 24 0m-24 0 4 1m20-1-4 1M36 24a4 4 0 1 1-8 0 4 4 0 1 1 8 0Z',
  },
  sacrifice_gambit: {
    name: '弃舰筹谋', commanderId: 'guihang', primary: '#e2aa52', accent: '#fff0b5', surface: '#342921',
    path: 'M35 10h15v21H35zM39 10V6h16v21h-5M11 30l9 5 3-8 9 5-3 8 11 5-9 8-16-8-4-15Zm-5 19q8-3 14 1t15 2 15 2m-43 4q7-3 14 1t14 1',
  },
} as const

export type CommanderSkillId = keyof typeof skills

export function commanderSkillVisual(id: unknown) {
  if (typeof id !== 'string' || !Object.hasOwn(skills, id)) return null
  const skillId = id as CommanderSkillId
  return { id: skillId, ...skills[skillId] }
}

export function chainCommanderSkillId(entry: Record<string, unknown>, name: string): CommanderSkillId | undefined {
  if (entry.item_kind && entry.item_kind !== 'commander_skill') return undefined
  const visual = commanderSkillVisual(entry.skill_id)
  if (visual) return visual.id
  // 旧录像中的已知技能可能只有名称。
  return (Object.keys(skills) as CommanderSkillId[]).find(id => skills[id].name === name)
}
