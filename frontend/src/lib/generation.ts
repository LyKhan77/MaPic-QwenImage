// Konstanta awal sebelum kalibrasi. Ganti dengan angka nyata dari smoke test
// Fase 0 (lihat docs/superpowers/plans/2026-09-21-qwen-image-2.1-migration.md Task 3.4).
const BASE_SECONDS = 8
const SECONDS_PER_STEP_1K = 1.2
const REF_SECONDS = 3
const CFG_MULTIPLIER = 1.9

export function estimateTotalSeconds(
  steps: number,
  numRefImages: number,
  resolution: number = 2048,
  cfgEnabled: boolean = false,
): number {
  const scaleFactor = resolution >= 2048 ? 3.5 : 1
  const base = BASE_SECONDS + steps * SECONDS_PER_STEP_1K * scaleFactor
  const refOverhead = numRefImages > 0 ? 5 + numRefImages * REF_SECONDS : 0
  const cfgFactor = cfgEnabled ? CFG_MULTIPLIER : 1
  return Math.round((base + refOverhead) * cfgFactor)
}
