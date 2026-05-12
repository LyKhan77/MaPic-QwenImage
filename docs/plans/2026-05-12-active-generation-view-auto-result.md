# Fix Active Generation View And Auto-Result

## Summary
- Fix `New Generation` during active work so it opens a clean prompt view instead of being forced back to the loader.
- Auto-open the newest completed result when active generation work finishes, including after browser refresh during generation.

## Key Changes
- Make active-loader display explicit in `Dashboard.tsx` via `shouldShowActiveGenerationView()`.
- Track a new-generation draft state so active work can continue in the background.
- Detect current-user generation completion and refetch history to show the newest result.
- Keep active indicator focus behavior for returning to the loader/progress view.

## Test Plan
- `cd frontend && npm run check:active-generations`
- `cd frontend && npm run build`
- Manual: start generation, click `New Generation`, submit another prompt, verify active indicator updates, and verify completed result opens automatically.

## Assumptions
- When all current-user active jobs finish, the latest PNG history item is the result to open.
- No backend API changes are required.
