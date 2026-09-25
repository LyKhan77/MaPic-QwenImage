// Filter riwayat sisi klien: daftar sudah ada di memori, jadi pencarian tidak
// perlu endpoint atau fetch baru.

export function filterHistory<T extends { prompt: string }>(items: T[], query: string): T[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return items
  return items.filter(item => item.prompt.toLowerCase().includes(needle))
}
