export interface DailyChallengeView {
  date: string
  next_reset_at: number
  status: 'available' | 'in_progress' | 'completed' | 'failed' | 'unavailable' | 'unauthorized'
  puzzle: { puzzle_id: string; name: string; difficulty: string } | null
  rewards: { tide: number; xp: number }
  room_id?: string | null
  reason?: string
}
