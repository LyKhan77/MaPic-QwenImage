export interface Generation {
  id: string
  user_id: string
  prompt: string
  image_path: string
  public_url: string
  created_at: string
}

export interface ActiveGeneration {
  id: string
  user_id: string
  prompt: string
  elapsed_seconds: number
  status?: 'queued' | 'running' | 'saving'
  num_inference_steps?: number
  num_ref_images?: number
  resolution?: number
  cfg_enabled?: boolean
}

export interface GenerationTimeParams {
  steps: number
  numRefImages: number
  resolution: number
  cfgEnabled: boolean
}
