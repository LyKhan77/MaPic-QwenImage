const API_URL = import.meta.env.VITE_API_URL
  || `http://${window.location.hostname}:8181/api`

export type ModelStatus = 'ready' | 'loading' | 'offline' | 'unloaded'

export const api = {
  async getHealth(): Promise<ModelStatus> {
    try {
      const res = await fetch(`${API_URL}/health`)
      if (!res.ok) return 'offline'
      const data = await res.json()
      return data.status as ModelStatus
    } catch {
      return 'offline'
    }
  },

  async loadModel(onProgress?: (progress: number, message: string) => void) {
    if (!onProgress) {
      const res = await fetch(`${API_URL}/load`, { method: 'POST' })
      if (!res.ok) throw new Error('Failed to load model')
      return res.json()
    }

    return new Promise((resolve, reject) => {
      const eventSource = new EventSource(`${API_URL}/load/stream`);
      
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.error) {
            eventSource.close();
            reject(new Error(data.message));
          } else {
            onProgress(data.progress, data.message);
            if (data.progress === 100) {
              eventSource.close();
              resolve({ status: 'ready' });
            }
          }
        } catch (e) {
          eventSource.close();
          reject(e);
        }
      };

      eventSource.onerror = (error) => {
        eventSource.close();
        reject(error);
      };
    });
  },

  async unloadModel() {
    const res = await fetch(`${API_URL}/unload`, { method: 'POST' })
    if (!res.ok) throw new Error('Failed to unload model')
    return res.json()
  },

  async getHistory(userId: string) {
    const res = await fetch(`${API_URL}/history/${userId}`)
    if (!res.ok) throw new Error('Failed to fetch history')
    return res.json()
  },

  async generateImage(prompt: string, userId: string, images?: string[], options?: { num_inference_steps?: number; guidance_scale?: number }) {
    const body: Record<string, unknown> = { prompt, user_id: userId }
    if (images) body.images = images
    if (options?.num_inference_steps) body.num_inference_steps = options.num_inference_steps
    if (options?.guidance_scale) body.guidance_scale = options.guidance_scale

    const res = await fetch(`${API_URL}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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

  async deleteHistory(id: string) {
    const res = await fetch(`${API_URL}/history/${id}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error('Failed to delete item')
    return res.json()
  },

  async getGenerationStatus(): Promise<{ stage: string; step: number; total_steps: number }> {
    try {
      const res = await fetch(`${API_URL}/generations/status`)
      if (!res.ok) return { stage: 'idle', step: 0, total_steps: 0 }
      return res.json()
    } catch {
      return { stage: 'idle', step: 0, total_steps: 0 }
    }
  },

  async getActiveGenerations() {
    try {
      const res = await fetch(`${API_URL}/generations/active`)
      if (!res.ok) return []
      return res.json()
    } catch {
      return []
    }
  },

  async getLoadState(): Promise<{ status: string; segment_index: number; segment_progress: number; progress: number; message: string }> {
    try {
      const res = await fetch(`${API_URL}/load/state`)
      if (!res.ok) return { status: 'offline', segment_index: 0, segment_progress: 0, progress: 0, message: '' }
      return res.json()
    } catch {
      return { status: 'offline', segment_index: 0, segment_progress: 0, progress: 0, message: '' }
    }
  }

  async getTunnelStatus(): Promise<{ tunnel_url: string | null; vercel_dashboard: string }> {
    try {
      const res = await fetch(`${API_URL}/tunnel-status`)
      if (!res.ok) return { tunnel_url: null, vercel_dashboard: '' }
      return res.json()
    } catch {
      return { tunnel_url: null, vercel_dashboard: '' }
    }
  }
}
