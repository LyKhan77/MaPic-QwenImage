export interface GpuNodeInfo {
  id: string
  name: string
  vram_total_mb: number
  vram_free_mb: number
  online: boolean
  loaded: boolean
  active: boolean
  default: boolean
}

export interface GpuNodesResponse {
  active_gpu: string | null
  default_gpu: string | null
  gpus: GpuNodeInfo[]
}

export function formatVramGb(mb: number): string {
  if (!Number.isFinite(mb) || mb <= 0) return '0.0 GB'
  return `${(mb / 1024).toFixed(1)} GB`
}

export function formatGpuShortName(name: string): string {
  return name.replace(/^NVIDIA\s+GeForce\s+/i, '').replace(/^NVIDIA\s+/i, '').trim() || name
}

export function canSelectGpuNode(
  node: GpuNodeInfo,
  options: { modelStatus: string; hasActiveGeneration: boolean },
): boolean {
  if (!node.online) return false
  if (options.modelStatus === 'loading') return false
  if (options.hasActiveGeneration) return false
  if (node.active && node.loaded && options.modelStatus === 'ready') return false
  return true
}
