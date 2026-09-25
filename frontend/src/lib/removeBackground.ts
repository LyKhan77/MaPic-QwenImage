// Helper murni untuk toggle Remove Background. Sengaja tanpa React supaya bisa
// diperiksa `frontend/scripts/check-remove-background-ui.mjs`.

// Label yang dipakai server saat menyimpan hasil cutout ke riwayat; satu-satunya
// penanda jenis hasil karena tidak ada kolom DB baru.
export const REMOVE_BACKGROUND_LABEL = 'Remove background'

// Pemisah label cutout dan nama sumbernya (em dash U+2014). Satu-satunya tempat
// literal ini ditulis; dipakai deteksi maupun pengupasan prefiks.
const CUTOUT_LABEL_SEPARATOR = ' — '

export type RemoveBackgroundBlockReason = 'no-image' | 'too-many' | 'reading'

// Gambar hasil riwayat dan unggahan membawa prefix `data:...;base64,`; endpoint
// hanya menerima base64 telanjang.
export function stripDataUrlPrefix(value: string): string {
  const commaIndex = value.indexOf(',')
  return value.startsWith('data:') && commaIndex !== -1 ? value.slice(commaIndex + 1) : value
}

// Cutout memakai tepat satu gambar: tanpa gambar tidak ada yang dipotong, dan
// lebih dari satu tidak punya arti (tidak ada yang digabung maupun dipilih).
export function canSubmitRemoveBackground(
  images: { id: string; base64: string }[],
  isReading: boolean,
): { ok: boolean; reason?: RemoveBackgroundBlockReason } {
  if (isReading) return { ok: false, reason: 'reading' }
  if (images.length === 0) return { ok: false, reason: 'no-image' }
  if (images.length > 1) return { ok: false, reason: 'too-many' }
  return { ok: true }
}

export function removeBackgroundSendLabel(isBusy: boolean): string {
  return isBusy ? 'REMOVING...' : 'REMOVE BG'
}

const isSuffixedCutoutLabel = (prompt?: string | null): boolean =>
  (prompt ?? '').startsWith(`${REMOVE_BACKGROUND_LABEL}${CUTOUT_LABEL_SEPARATOR}`)

export function isCutoutGeneration(prompt?: string | null): boolean {
  // Baris lama hanya punya label telanjang; yang baru menambahkan em dash + nama
  // sumber, jadi deteksi berbasis prefiks dan bukan kesamaan persis.
  return prompt === REMOVE_BACKGROUND_LABEL || isSuffixedCutoutLabel(prompt)
}

// Label sumber untuk cutout baru. Prompt riwayat yang **sudah** label cutout
// dikupas jadi nama sumbernya saja: tanpa ini label menumpuk
// (`Remove background — Remove background — cocacola.png`). Teks yang hanya
// mirip pembuka kata tetap utuh karena pengupasan menuntut label telanjang
// persis atau prefiks label + em dash.
export function cutoutLabelFromPrompt(prompt?: string | null): string | undefined {
  if (!prompt) return undefined
  if (prompt === REMOVE_BACKGROUND_LABEL) return undefined
  if (!isSuffixedCutoutLabel(prompt)) return prompt
  const source = prompt.slice(`${REMOVE_BACKGROUND_LABEL}${CUTOUT_LABEL_SEPARATOR}`.length).trim()
  return source === '' ? undefined : source
}
