# Multi-Generation Global Queue Plan

## Summary
- Allow users to submit additional prompts while generation is active.
- Keep the active loading canvas read-only, but let New Generation open one clean prompt input.
- Show multiple accepted jobs per user in the active generations indicator with a `/10` global capacity count.

## Implementation
- Replace local sequential queue draining with concurrent backend requests, so every accepted job is tracked by backend active generation state.
- Use backend `/api/generate` capacity limit as the global queue limit.
- Keep optimistic current-user entries visible in the indicator until backend polling returns the accepted jobs.
- Preserve one prompt input per page state: empty prompt page, generated result page, or read-only loading page.

## Verification
- Frontend build should pass.
- Backend capacity unit test should still pass.
- Manual check: generate, click New Generation, submit another prompt, confirm indicator shows multiple user entries and loading page has no input.
