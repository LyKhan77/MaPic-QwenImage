import { supabase } from './supabase'

const API_URL = import.meta.env.VITE_API_URL
  || `http://${window.location.hostname}:8281/api`

export type ModelStatus = 'ready' | 'loading' | 'offline' | 'unloaded'

// Backend memverifikasi token Supabase dan mengambil identitas user dari claim
// `sub`; user_id yang dikirim klien tidak pernah dipercaya.
async function authHeaders(json = false): Promise<Record<string, string>> {
  const { data: { session } } = await supabase.auth.getSession()
  const headers: Record<string, string> = {}
  if (json) headers['Content-Type'] = 'application/json'
  if (session) headers.Authorization = `Bearer ${session.access_token}`
  return headers
}

export const api = {
  async getHealth(): Promise<ModelStatus> {
    try {
      const res = await fetch(`${API_URL}/health`, { headers: await authHeaders() })
      if (!res.ok) return 'offline'
      const data = await res.json()
      return data.status as ModelStatus
    } catch {
      return 'offline'
    }
  },

  async loadModel() {
    const res = await fetch(`${API_URL}/load`, { method: 'POST', headers: await authHeaders() })
    if (!res.ok) throw new Error('Failed to load model')
    return res.json()
  },

  async unloadModel() {
    const res = await fetch(`${API_URL}/unload`, { method: 'POST', headers: await authHeaders() })
    if (!res.ok) throw new Error('Failed to unload model')
    return res.json()
  },

  async getHistory(userId: string) {
    const res = await fetch(`${API_URL}/history/${userId}`, { headers: await authHeaders() })
    if (!res.ok) throw new Error('Failed to fetch history')
    return res.json()
  },

  async generateImage(
    prompt: string,
    images?: string[],
    options?: { num_inference_steps?: number; true_cfg_scale?: number; negative_prompt?: string; resolution?: 1024 | 2048 },
  ) {
    const body: Record<string, unknown> = { prompt }
    if (images) body.images = images
    if (options?.num_inference_steps) body.num_inference_steps = options.num_inference_steps
    if (options?.true_cfg_scale) body.true_cfg_scale = options.true_cfg_scale
    if (options?.negative_prompt) body.negative_prompt = options.negative_prompt
    if (options?.resolution) body.resolution = options.resolution

    const res = await fetch(`${API_URL}/generate`, {
      method: 'POST',
      headers: await authHeaders(true),
      body: JSON.stringify(body),
    })

    if (!res.ok) {
        let errorMessage = 'Failed to generate image';
        try {
            const errorData = await res.json();
            if (errorData.detail) errorMessage = errorData.detail;
        } catch {
            // ignore JSON parse error
        }
        throw new Error(errorMessage)
    }
    return res.json()
  },

  // Jalur CPU terpisah dari Qwen: satu gambar base64 tanpa prefix data-URL,
  // hasilnya Generation baru di riwayat. `sourceLabel` hanya nama tampilan yang
  // dipakai server sebagai penanda baris riwayat, bukan validasi apa pun.
  async removeBackground(image: string, sourceLabel?: string) {
    const body: Record<string, unknown> = { image }
    if (sourceLabel) body.source_label = sourceLabel

    const res = await fetch(`${API_URL}/remove-background`, {
      method: 'POST',
      headers: await authHeaders(true),
      body: JSON.stringify(body),
    })

    if (!res.ok) {
        let errorMessage = 'Failed to remove background';
        try {
            const errorData = await res.json();
            if (errorData.detail) errorMessage = errorData.detail;
        } catch {
            // ignore JSON parse error
        }
        throw new Error(errorMessage)
    }
    return res.json()
  },

  async deleteHistory(id: string) {
    const res = await fetch(`${API_URL}/history/${id}`, {
      method: 'DELETE',
      headers: await authHeaders(),
    })
    if (!res.ok) throw new Error('Failed to delete item')
    return res.json()
  },

  async getGenerationStatus(): Promise<{ stage: string; step: number; total_steps: number }> {
    try {
      const res = await fetch(`${API_URL}/generations/status`, { headers: await authHeaders() })
      if (!res.ok) return { stage: 'idle', step: 0, total_steps: 0 }
      return res.json()
    } catch {
      return { stage: 'idle', step: 0, total_steps: 0 }
    }
  },

  async getActiveGenerations() {
    try {
      const res = await fetch(`${API_URL}/generations/active`, { headers: await authHeaders() })
      if (!res.ok) return []
      return res.json()
    } catch {
      return []
    }
  },

  async getLoadState(): Promise<{ status: string; segment_index: number; segment_progress: number; progress: number; message: string }> {
    try {
      const res = await fetch(`${API_URL}/load/state`, { headers: await authHeaders() })
      if (!res.ok) return { status: 'offline', segment_index: 0, segment_progress: 0, progress: 0, message: '' }
      return res.json()
    } catch {
      return { status: 'offline', segment_index: 0, segment_progress: 0, progress: 0, message: '' }
    }
  }
}
