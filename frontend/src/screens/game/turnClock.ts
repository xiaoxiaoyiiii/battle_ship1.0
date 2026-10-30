/**
 * Turn clock view model (ticket #47).
 *
 * The server owns the deadline (contract field `turn_deadline`, epoch ms) and
 * the configured timeout (`turn_timeout_seconds`). This module only formats
 * them: it never derives a second deadline and it hides the clock when either
 * field is missing, so a client can never invent a countdown the server is not
 * running (spec §5 "字段缺失时隐藏计时，不猜").
 */

export interface TurnClockView {
  /** Render the clock at all? False when the server sent no timed turn. */
  visible: boolean
  /** Whole seconds left, never negative. */
  remaining: number
  /** Configured turn length in seconds (0 when unknown). */
  total: number
  /** Last 10 seconds: the status band switches to the warning tone. */
  warning: boolean
  /** The deadline has passed; the server's fallback action is in flight. */
  expired: boolean
  /** mm:ss for the status band. */
  label: string
}

export const CLOCK_WARNING_SECONDS = 10

export function turnClockView(
  deadline: number | null | undefined,
  timeoutSeconds: number | null | undefined,
  now: number,
): TurnClockView {
  const total = Number(timeoutSeconds)
  const end = Number(deadline)
  const visible = Number.isFinite(end) && end > 0 && Number.isFinite(total) && total > 0
  if (!visible) {
    return { visible: false, remaining: 0, total: 0, warning: false, expired: false, label: '' }
  }
  const remaining = Math.max(0, Math.ceil((end - now) / 1000))
  return {
    visible: true,
    remaining,
    total,
    warning: remaining > 0 && remaining <= CLOCK_WARNING_SECONDS,
    expired: remaining <= 0,
    label: formatClock(remaining),
  }
}

/** mm:ss, clamped to the configured turn length so a skewed clock cannot show 99:99. */
export function formatClock(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(safe / 60)
  const rest = safe % 60
  return String(minutes).padStart(2, '0') + ':' + String(rest).padStart(2, '0')
}
