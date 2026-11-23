export type PlatformBadgeValue = 'PC' | 'Steam' | 'PS4' | 'PS5' | 'Switch' | ''

export const PLATFORM_OPTIONS: { value: PlatformBadgeValue; label: string }[] = [
  { value: 'PC', label: 'PC' },
  { value: 'Steam', label: 'Steam' },
  { value: 'PS4', label: 'PS4' },
  { value: 'PS5', label: 'PS5' },
  { value: 'Switch', label: 'Switch' },
  { value: '', label: '无' },
]

const CANONICAL_MAP: Record<string, PlatformBadgeValue> = {
  pc: 'PC',
  steam: 'Steam',
  ps4: 'PS4',
  ps5: 'PS5',
  switch: 'Switch',
  nsw: 'Switch',
}

const LEGACY_SCRAPER_NAMES = new Set([
  'aggregated',
  'multi',
  'vndb',
  'bgm',
  'bangumi',
  'ymgal',
  'kungal',
  'dlsite',
  'igdb',
  'tgal',
  'touchgal',
  'sgdb',
  'steamgriddb',
  'local',
])

/**
 * 将数据库中的平台值（含历史刮削源旧值）优雅映射为发行/游玩平台角标
 */
export function normalizePlatformBadge(
  raw?: string | null,
  externalIds?: Record<string, string> | null,
): PlatformBadgeValue {
  if (raw === '') return ''
  const trimmed = (raw ?? '').trim()
  if (!trimmed) return ''

  const low = trimmed.toLowerCase()
  if (low in CANONICAL_MAP) {
    return CANONICAL_MAP[low]
  }
  if (LEGACY_SCRAPER_NAMES.has(low)) {
    if (externalIds && String(externalIds.steam || '').trim()) {
      return 'Steam'
    }
    return 'PC'
  }
  return 'PC'
}

export interface SpinePlatformBadgeStyle {
  label: string
  bg: string
  color: string
}

export function getSpinePlatformBadge(
  raw?: string | null,
  externalIds?: Record<string, string> | null,
): SpinePlatformBadgeStyle | null {
  const canonical = normalizePlatformBadge(raw, externalIds)
  if (!canonical) return null

  const map: Record<Exclude<PlatformBadgeValue, ''>, SpinePlatformBadgeStyle> = {
    PC: { label: 'PC', bg: '#e4e4e7', color: '#0a0a0c' },
    Steam: { label: 'STEAM', bg: '#38bdf8', color: '#0a0a0c' },
    PS4: { label: 'PS4', bg: '#60a5fa', color: '#0a0a0c' },
    PS5: { label: 'PS5', bg: '#f4f4f5', color: '#0a0a0c' },
    Switch: { label: 'SWITCH', bg: '#fb7185', color: '#0a0a0c' },
  }
  return map[canonical]
}
