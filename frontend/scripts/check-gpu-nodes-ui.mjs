import assert from 'node:assert/strict'
import { canSelectGpuNode, formatGpuShortName, formatVramGb } from '../src/lib/gpuNodes.ts'

assert.equal(formatVramGb(16303), '15.9 GB')
assert.equal(formatVramGb(0), '0.0 GB')
assert.equal(formatVramGb(-10), '0.0 GB')

assert.equal(formatGpuShortName('NVIDIA GeForce RTX 5080'), 'RTX 5080')
assert.equal(formatGpuShortName('NVIDIA A100'), 'A100')
assert.equal(formatGpuShortName('GPU 2'), 'GPU 2')

const gpu1 = {
  id: '1',
  name: 'NVIDIA GeForce RTX 5080',
  vram_total_mb: 16303,
  vram_free_mb: 15923,
  online: true,
  loaded: false,
  active: false,
  default: false,
}

const gpu2Ready = {
  id: '2',
  name: 'NVIDIA GeForce RTX 5080',
  vram_total_mb: 16303,
  vram_free_mb: 15881,
  online: true,
  loaded: true,
  active: true,
  default: true,
}

const gpuOffline = { ...gpu1, online: false }

assert.equal(canSelectGpuNode(gpu1, { modelStatus: 'ready', hasActiveGeneration: false }), true)
assert.equal(canSelectGpuNode(gpu2Ready, { modelStatus: 'ready', hasActiveGeneration: false }), false)
assert.equal(canSelectGpuNode({ ...gpu2Ready, loaded: false }, { modelStatus: 'unloaded', hasActiveGeneration: false }), true)
assert.equal(canSelectGpuNode(gpu1, { modelStatus: 'loading', hasActiveGeneration: false }), false)
assert.equal(canSelectGpuNode(gpu1, { modelStatus: 'ready', hasActiveGeneration: true }), false)
assert.equal(canSelectGpuNode(gpuOffline, { modelStatus: 'ready', hasActiveGeneration: false }), false)

console.log('gpuNodes: formatVramGb, formatGpuShortName, canSelectGpuNode OK')
