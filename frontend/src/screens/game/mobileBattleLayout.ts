/** 手机舞台只依赖视口，读牌、日志和状态更新均不参与尺寸计算。 */
export function mobileBattleLayout(width: number, height: number, navHeight: number) {
  const landscape = width > height
  const railWidth = landscape ? (width < 800 ? 156 : 180) : 0
  const safeHeight = Math.max(0, height - navHeight)
  const boardSize = landscape
    ? Math.floor(Math.min((width - railWidth - 44) / 2, safeHeight - 82))
    : Math.floor(Math.max(246, Math.min(width - 24, safeHeight - 502)))
  return {
    mode: landscape ? 'side' as const : 'tabs' as const,
    landscape,
    boardSize: Math.max(180, boardSize),
    railWidth,
    handHeight: 166,
  }
}
