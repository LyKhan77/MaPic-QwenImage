import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  REMOVE_BACKGROUND_LABEL,
  canSubmitRemoveBackground,
  isCutoutGeneration,
  removeBackgroundSendLabel,
  stripDataUrlPrefix,
} from '../src/lib/removeBackground.ts'
import { filterHistory } from '../src/lib/historySearch.ts'

const one = [{ id: 'a', base64: 'data:image/png;base64,AAA' }]
const two = [...one, { id: 'b', base64: 'data:image/png;base64,BBB' }]

assert.equal(stripDataUrlPrefix('data:image/png;base64,AAAA'), 'AAAA')
assert.equal(stripDataUrlPrefix('data:image/jpeg;base64,/9j/4A=='), '/9j/4A==')
assert.equal(stripDataUrlPrefix('AAAA'), 'AAAA')
assert.equal(stripDataUrlPrefix(''), '')

assert.deepEqual(canSubmitRemoveBackground(one, false), { ok: true })
assert.deepEqual(canSubmitRemoveBackground([], false), { ok: false, reason: 'no-image' })
assert.deepEqual(canSubmitRemoveBackground(two, false), { ok: false, reason: 'too-many' })
assert.deepEqual(canSubmitRemoveBackground(one, true), { ok: false, reason: 'reading' })
// Membaca gambar menang atas kekurangan gambar: satu pesan saja yang ditampilkan.
assert.deepEqual(canSubmitRemoveBackground([], true), { ok: false, reason: 'reading' })

assert.equal(isCutoutGeneration(REMOVE_BACKGROUND_LABEL), true)
assert.equal(isCutoutGeneration(`${REMOVE_BACKGROUND_LABEL} — cocacola.jpg`), true)
assert.equal(isCutoutGeneration('remove background'), false)
assert.equal(isCutoutGeneration('Remove Background'), false)
assert.equal(isCutoutGeneration('Remove background please'), false)
assert.equal(isCutoutGeneration('Remove background of my photo'), false)
assert.equal(isCutoutGeneration('make a remove background poster'), false)
assert.equal(isCutoutGeneration(undefined), false)
assert.equal(isCutoutGeneration(null), false)
assert.equal(isCutoutGeneration(''), false)

assert.equal(removeBackgroundSendLabel(false), 'REMOVE BG')
assert.equal(removeBackgroundSendLabel(true), 'REMOVING...')

console.log('removeBackground: stripDataUrlPrefix OK')
console.log('removeBackground: canSubmitRemoveBackground 4 outcomes OK')
console.log('removeBackground: isCutoutGeneration legacy + suffixed label OK')
console.log('removeBackground: removeBackgroundSendLabel busy/idle OK')

// Pencarian riwayat dijalankan di klien atas array `history` yang sudah ada.
const historyItems = [
  { id: '1', prompt: 'Remove background — Cocacola.jpg' },
  { id: '2', prompt: 'A red balloon at dusk' },
  { id: '3', prompt: 'remove background' },
]
assert.deepEqual(filterHistory(historyItems, ''), historyItems)
assert.deepEqual(filterHistory(historyItems, '   '), historyItems)
assert.deepEqual(filterHistory(historyItems, 'BALLOON').map(item => item.id), ['2'])
assert.deepEqual(filterHistory(historyItems, 'cocacola').map(item => item.id), ['1'])
assert.deepEqual(filterHistory(historyItems, 'nothing here'), [])
const beforeFilter = historyItems.map(item => item.prompt)
filterHistory(historyItems, 'balloon')
assert.deepEqual(historyItems.map(item => item.prompt), beforeFilter)
assert.deepEqual(filterHistory([], 'balloon'), [])
console.log('historySearch: filterHistory empty/case-insensitive/no-match/no-mutate OK')

// Mode cutout harus dimiliki Dashboard: PromptInput dipasang dua tempat yang
// saling menggantikan (terpusat dan bar bawah), jadi state lokal di sini akan
// ter-reset ke false setiap pengguna memilih sumber dari riwayat.
const readSource = (relative) =>
  readFileSync(new URL(relative, import.meta.url), 'utf8')
const promptInputSource = readSource('../src/components/PromptInput.tsx')
const dashboardSource = readSource('../src/pages/Dashboard.tsx')
const imageCanvasSource = readSource('../src/components/ImageCanvas.tsx')
const sidebarSource = readSource('../src/components/Sidebar.tsx')

assert.equal(/\[removeBg, setRemoveBg\]/.test(promptInputSource), false)
assert.match(promptInputSource, /removeBg: boolean/)
assert.match(promptInputSource, /onRemoveBgChange: \(next: boolean\) => void/)
assert.match(promptInputSource, /onRemoveBgChange\(!removeBg\)/)

assert.match(dashboardSource, /const \[removeBg, setRemoveBg\] = useState\(false\)/)
assert.match(imageCanvasSource, /removeBg={removeBg}/)
assert.match(imageCanvasSource, /onRemoveBgChange={onRemoveBgChange}/)
// Dua jalur pemasangan PromptInput di Dashboard (lewat ImageCanvas dan bar
// bawah) harus menerima prop yang sama.
assert.equal((dashboardSource.match(/removeBg={removeBg}/g) ?? []).length, 2)
assert.equal((dashboardSource.match(/onRemoveBgChange={setRemoveBg}/g) ?? []).length, 2)
const barPromptInputSource = dashboardSource.slice(dashboardSource.indexOf('<PromptInput'))
assert.match(barPromptInputSource, /removeBg={removeBg}/)
assert.match(barPromptInputSource, /onRemoveBgChange={setRemoveBg}/)
assert.match(dashboardSource, /setRemoveBg\(false\)/)

console.log('removeBackground: removeBg owned by Dashboard, forwarded to both inputs OK')

// Label sumber: nama berkas diunggah dikirim ke server; bila tidak ada, label
// diambil dari prompt item riwayat yang sedang dipilih.
const labelSignature = /onRemoveBackground\?: \(imageBase64: string, sourceLabel\?: string\)/
assert.match(promptInputSource, labelSignature)
assert.match(imageCanvasSource, labelSignature)
assert.match(dashboardSource, /handleRemoveBackground = useCallback\(async \(imageBase64: string, sourceLabel\?: string\)/)
assert.match(dashboardSource, /sourceLabel \?\? currentGen\?\.prompt/)
assert.match(promptInputSource, /name: file\.name/)
assert.match(promptInputSource, /images\[0\]\.name/)

// Baris riwayat satu baris + tooltip di semua lebar, dan kotak pencarian hanya
// di layout lebar (rail 80px tidak punya ruang).
assert.match(sidebarSource, /title=\{item\.prompt\}/)
assert.match(sidebarSource, /truncate text-sm font-medium/)
assert.equal(/line-clamp-2/.test(sidebarSource), false)
assert.match(sidebarSource, /type="search"/)
assert.match(sidebarSource, /aria-label="Search history"/)
assert.match(sidebarSource, /filterHistory\(history, query\)/)
assert.match(sidebarSource, /No matches\./)

console.log('removeBackground: source label threaded + sidebar one-line/search OK')
