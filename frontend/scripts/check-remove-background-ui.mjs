import assert from 'node:assert/strict'
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
