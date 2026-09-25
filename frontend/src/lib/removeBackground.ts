// Helper murni untuk toggle Remove Background. Sengaja tanpa React supaya bisa
// diperiksa `frontend/scripts/check-remove-background-ui.mjs`.

// Label yang dipakai server saat menyimpan hasil cutout ke riwayat; satu-satunya
// penanda jenis hasil karena tidak ada kolom DB baru.
export const REMOVE_BACKGROUND_LABEL = 'Remove background'

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

export function isCutoutGeneration(prompt?: string | null): boolean {
  return prompt === REMOVE_BACKGROUND_LABEL
}
