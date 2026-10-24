export const qualityOptions = [240, 360, 480, 720, 1080, 1440, 2160].map(height => ({
  value: `${height}p`, label: `Up to ${height}p`
})).concat([{ value: 'best', label: 'Best available (no resolution limit)' }])
