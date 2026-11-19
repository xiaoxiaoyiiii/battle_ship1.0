import firepowerControl from '../../assets/commander-skills/firepower-control.webp'
import delayedLock from '../../assets/commander-skills/delayed-lock.webp'
import dauntlessFleet from '../../assets/commander-skills/dauntless-fleet.webp'
import sacrificeGambit from '../../assets/commander-skills/sacrifice-gambit.webp'
import type { CommanderSkillId } from './commanderSkillVisuals'

export const commanderSkillArt: Record<CommanderSkillId, string> = {
  firepower_control: firepowerControl,
  delayed_lock: delayedLock,
  dauntless_fleet: dauntlessFleet,
  sacrifice_gambit: sacrificeGambit,
}

const images = new Map<CommanderSkillId, HTMLImageElement>()

export function commanderSkillImage(id: CommanderSkillId): HTMLImageElement {
  let image = images.get(id)
  if (!image) {
    image = new Image()
    image.src = commanderSkillArt[id]
    images.set(id, image)
  }
  return image
}

export function preloadCommanderSkillArt() {
  const ids = Object.keys(commanderSkillArt) as CommanderSkillId[]
  return Promise.allSettled(ids.map(id => commanderSkillImage(id).decode()))
}
