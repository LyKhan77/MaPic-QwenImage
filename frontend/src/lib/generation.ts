export function estimateTotalSeconds(steps: number, numRefImages: number): number {
  const base = 45
  const diffusion = steps * 4.5
  const i2iOverhead = numRefImages > 0 ? 25 + numRefImages * 15 : 0
  return Math.round(base + diffusion + i2iOverhead)
}
