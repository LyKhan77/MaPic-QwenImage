# Read-Only Loading Prompt Fix

## Summary
- Remove prompt inputs from the generation loading screen.
- Prevent New Generation from showing an editable empty state while a generation is active.
- Keep prompt input visible only before submit and on generated result pages.

## Implementation
- Render the bottom result composer only when a completed `currentGen` exists.
- Keep `PromptInput` disabled when `isLoading` is true as a defensive guard.
- Make New Generation focus the active loading view when a generation is already pending.
- Update README and AGENTS to document the read-only loading workflow.

## Verification
- Frontend build should pass.
- Manual UI check should show zero prompt inputs on loading screen and exactly one prompt input on empty/result pages.
