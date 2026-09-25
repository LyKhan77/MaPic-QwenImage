import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  REMOVE_BACKGROUND_LABEL,
  canSubmitRemoveBackground,
  isCutoutGeneration,
  removeBackgroundSendLabel,
  stripDataUrlPrefix,
} from '../src/lib/removeBackground.ts'

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
assert.equal(isCutoutGeneration('remove background'), false)
assert.equal(isCutoutGeneration('Remove Background'), false)
assert.equal(isCutoutGeneration('Remove background please'), false)
assert.equal(isCutoutGeneration(undefined), false)
assert.equal(isCutoutGeneration(null), false)
assert.equal(isCutoutGeneration(''), false)

assert.equal(removeBackgroundSendLabel(false), 'REMOVE BG')
assert.equal(removeBackgroundSendLabel(true), 'REMOVING...')

console.log('removeBackground: stripDataUrlPrefix OK')
console.log('removeBackground: canSubmitRemoveBackground 4 outcomes OK')
console.log('removeBackground: isCutoutGeneration exact-label-only OK')
console.log('removeBackground: removeBackgroundSendLabel busy/idle OK')

// Mode cutout harus dimiliki Dashboard: PromptInput dipasang dua tempat yang
// saling menggantikan (terpusat dan bar bawah), jadi state lokal di sini akan
// ter-reset ke false setiap pengguna memilih sumber dari riwayat.
const readSource = (relative) =>
  readFileSync(new URL(relative, import.meta.url), 'utf8')
const promptInputSource = readSource('../src/components/PromptInput.tsx')
const dashboardSource = readSource('../src/pages/Dashboard.tsx')
const imageCanvasSource = readSource('../src/components/ImageCanvas.tsx')

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
