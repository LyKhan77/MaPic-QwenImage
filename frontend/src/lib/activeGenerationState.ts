import type { ActiveGeneration } from '../types'

export interface PendingGenerationSummary {
  prompt: string
  startedAt: number
}

export function shouldShowActiveGenerationView({
  currentGeneration,
  hasCurrentUserGenerationWork,
  isViewingActiveGeneration,
}: {
  currentGeneration: { public_url?: string | null } | null
  hasCurrentUserGenerationWork: boolean
  isViewingActiveGeneration: boolean
}): boolean {
  const hasRenderableGeneration = Boolean(currentGeneration?.public_url)
  return isViewingActiveGeneration && !hasRenderableGeneration && hasCurrentUserGenerationWork
}

export function didGenerationWorkComplete(
  hadCurrentUserGenerationWork: boolean,
  hasCurrentUserGenerationWork: boolean,
): boolean {
  return hadCurrentUserGenerationWork && !hasCurrentUserGenerationWork
}

export function getDisplayedGenerations(
  activeGenerations: ActiveGeneration[],
  pendingGenerations: Record<string, PendingGenerationSummary>,
  currentUserId: string,
  now: number,
): ActiveGeneration[] {
  const optimisticGenerations: ActiveGeneration[] = Object.entries(pendingGenerations)
    .filter(([, pending]) => !activeGenerations.some(gen =>
      gen.user_id === currentUserId && gen.prompt === pending.prompt
    ))
    .map(([id, pending]) => ({
      id,
      user_id: currentUserId,
      prompt: pending.prompt,
      elapsed_seconds: Math.max(0, Math.floor((now - pending.startedAt) / 1000)),
      status: 'queued',
    }))

  return [...activeGenerations, ...optimisticGenerations]
}

export function getUserActiveGenerations(
  activeGenerations: ActiveGeneration[],
  userId: string,
): ActiveGeneration[] {
  return activeGenerations.filter(gen => gen.user_id === userId)
}

export function hasGenerationWorkForUser(
  activeGenerations: ActiveGeneration[],
  pendingGenerations: Record<string, PendingGenerationSummary>,
  userId: string,
): boolean {
  return Object.keys(pendingGenerations).length > 0 || getUserActiveGenerations(activeGenerations, userId).length > 0
}

export function getActiveGenerationParams(
  activeGenerations: ActiveGeneration[],
  userId: string,
): { steps: number; numRefImages: number } | null {
  const activeGeneration = getUserActiveGenerations(activeGenerations, userId)[0]
  if (!activeGeneration) return null

  return {
    steps: activeGeneration.num_inference_steps ?? 50,
    numRefImages: activeGeneration.num_ref_images ?? 0,
  }
}
