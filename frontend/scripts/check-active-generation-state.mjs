import assert from 'node:assert/strict'
import {
  didGenerationWorkComplete,
  getActiveGenerationParams,
  getDisplayedGenerations,
  hasGenerationWorkForUser,
  shouldShowActiveGenerationView,
} from '../src/lib/activeGenerationState.ts'

const activeGenerations = [
  {
    id: 'job-user-1',
    user_id: 'user-1',
    prompt: 'first prompt',
    elapsed_seconds: 12,
    status: 'running',
    num_inference_steps: 35,
    num_ref_images: 0,
  },
  {
    id: 'job-user-2',
    user_id: 'user-2',
    prompt: 'second prompt',
    elapsed_seconds: 0,
    status: 'queued',
    num_inference_steps: 50,
    num_ref_images: 2,
  },
]

assert.equal(hasGenerationWorkForUser(activeGenerations, {}, 'user-2'), true)
assert.deepEqual(getActiveGenerationParams(activeGenerations, 'user-2'), {
  steps: 50,
  numRefImages: 2,
})

const displayed = getDisplayedGenerations(
  activeGenerations,
  {
    local: {
      prompt: 'local prompt',
      startedAt: 1_000,
    },
  },
  'user-2',
  4_500,
)

assert.equal(displayed.length, 3)
assert.deepEqual(displayed[2], {
  id: 'local',
  user_id: 'user-2',
  prompt: 'local prompt',
  elapsed_seconds: 3,
  status: 'queued',
})

assert.equal(shouldShowActiveGenerationView({
  currentGeneration: null,
  hasCurrentUserGenerationWork: true,
  isViewingActiveGeneration: true,
}), true)

assert.equal(shouldShowActiveGenerationView({
  currentGeneration: null,
  hasCurrentUserGenerationWork: true,
  isViewingActiveGeneration: false,
}), false)

assert.equal(shouldShowActiveGenerationView({
  currentGeneration: { id: 'completed' },
  hasCurrentUserGenerationWork: true,
  isViewingActiveGeneration: true,
}), false)

assert.equal(didGenerationWorkComplete(true, false), true)
assert.equal(didGenerationWorkComplete(true, true), false)
assert.equal(didGenerationWorkComplete(false, false), false)
