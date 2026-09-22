// Konstanta dari pengukuran nyata di server gspe-ai2 (Qwen-Image 2.1 Q8_0 + ComfyUI):
//   T2I 1K / 40 step          = 32,2 s
//   T2I 1K / 40 step / CFG 2  = 63,4 s
//   I2I 1K / 40 step / 1 ref  = 49,8 s
//   I2I 1K / 40 step / 3 ref  = 83,5 s
// Dari angka itu: base ~3 s, ~0,73 s per step pada 1K, ~17 s per gambar referensi,
// dan CFG mengalikan total dengan ~1,97.
const BASE_SECONDS = 3
const SECONDS_PER_STEP_1K = 0.73
const REF_SECONDS = 17
const CFG_MULTIPLIER = 1.97

// 2K belum pernah terukur: host ini memblokir resolusi di atas 1K (VRAM 16 GB).
// Angka ini hanya perkiraan kasar bila 2K diaktifkan di host lain.
const SCALE_FACTOR_2K = 3.5

export function estimateTotalSeconds(
  steps: number,
  numRefImages: number,
  resolution: number = 1024,
  cfgEnabled: boolean = false,
): number {
  const scaleFactor = resolution >= 2048 ? SCALE_FACTOR_2K : 1
  const base = BASE_SECONDS + steps * SECONDS_PER_STEP_1K * scaleFactor
  const refOverhead = numRefImages * REF_SECONDS
  const cfgFactor = cfgEnabled ? CFG_MULTIPLIER : 1
  return Math.round((base + refOverhead) * cfgFactor)
}
