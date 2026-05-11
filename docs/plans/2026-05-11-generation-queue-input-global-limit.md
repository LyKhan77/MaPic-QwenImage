# Generation Queue Input + Global Limit Plan

## Summary
- Keep the prompt composer usable while a generation is running so users can queue another prompt.
- Enforce a maximum of 10 active or accepted generation requests globally across all users.

## Implementation
- Render the bottom prompt input during active generation even when no completed image is selected.
- Allow prompt typing, reference attachment, settings changes, and queue submission while `isLoading` is true.
- Add `MAX_GLOBAL_GENERATIONS = 10` to the backend and reject `/api/generate` with HTTP 429 once active accepted jobs reach the limit.
- Document the queue workflow and global capacity in `README.md` and `AGENTS.md`.

## Verification
- Backend unit test covers capacity below the limit and rejection at the limit.
- Frontend build verifies TypeScript and production bundling.
