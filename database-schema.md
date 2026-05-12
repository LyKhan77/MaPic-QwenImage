# MaPic Database Schema

Last reviewed: 2026-05-12

This document describes the Supabase database and storage schema used by MaPic. It is based on the current codebase, not a live database introspection, because no Supabase migration files are present in this repository.

## Sources Reviewed

- `backend/services/supabase_service.py`
- `backend/schemas.py`
- `backend/main.py`
- `frontend/src/lib/supabase.ts`
- `frontend/src/types.ts`
- `API.md`

## Supabase Products Used

| Product | Usage |
| --- | --- |
| Auth | Frontend login/session management via Supabase Auth. |
| Postgres | Stores generated image history in `public.generations`. |
| Storage | Stores generated PNG files in the `generated_images` bucket. |

## Auth Model

MaPic uses Supabase Auth as the identity source. The frontend reads the authenticated session and sends `session.user.id` to the backend as `user_id`.

The backend uses `SUPABASE_SERVICE_ROLE_KEY` for database and storage operations, so API-level authorization is enforced by backend route behavior rather than by the browser calling PostgREST directly.

## Tables

### `public.generations`

Stores one row per completed image generation.

| Column | Type | Nullable | Default | Source / Purpose |
| --- | --- | --- | --- | --- |
| `id` | `uuid` | No | Expected: `gen_random_uuid()` | Generation record ID returned by API and used for deletion. |
| `user_id` | `uuid` | No | None | Owner user ID from Supabase Auth (`auth.users.id`). |
| `prompt` | `text` | No | None | User prompt. Backend validates request prompt length `1..2000`. |
| `image_path` | `text` | No | None | Internal Supabase Storage object path, format: `{user_id}/{uuid}.png`. |
| `public_url` | `text` | No | None | Public CDN URL returned by Supabase Storage. |
| `created_at` | `timestamptz` | No | Expected: `now()` | Used for history sorting, newest first. |

### Expected DDL

Use this as the canonical expected schema if recreating the database:

```sql
create extension if not exists "pgcrypto";

create table if not exists public.generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  prompt text not null check (char_length(prompt) between 1 and 2000),
  image_path text not null,
  public_url text not null,
  created_at timestamptz not null default now()
);

create index if not exists generations_user_created_at_idx
  on public.generations (user_id, created_at desc);
```

## Query Patterns

The backend currently performs these operations:

```sql
-- Insert completed generation
insert into public.generations (user_id, prompt, image_path, public_url)
values (:user_id, :prompt, :image_path, :public_url)
returning *;

-- Fetch user history
select *
from public.generations
where user_id = :user_id
order by created_at desc;

-- Find storage object before delete
select image_path
from public.generations
where id = :id
limit 1;

-- Delete generation row
delete from public.generations
where id = :id;
```

## Storage

### Bucket: `generated_images`

Stores generated PNG files.

| Property | Value |
| --- | --- |
| Bucket name | `generated_images` |
| Object path format | `{user_id}/{uuid}.png` |
| Content type | `image/png` |
| Public access | Required by current app because `public_url` is shown, downloaded, and copied from the frontend. |

Example object path:

```text
550e8400-e29b-41d4-a716-446655440000/8d96e57f-65af-46c5-8c19-ef4a3d0e7d29.png
```

## Storage Operations

The backend uses the service role key to:

- Upload generated PNG bytes to `generated_images`.
- Resolve a public URL for the uploaded object.
- Remove the object when a history item is deleted.

## Recommended RLS Policies

Because backend writes use the service role key, these policies mainly protect direct client access if `public.generations` is exposed through Supabase Data API.

```sql
alter table public.generations enable row level security;

create policy "Users can read their own generations"
on public.generations
for select
to authenticated
using (auth.uid() = user_id);

create policy "Users can delete their own generations"
on public.generations
for delete
to authenticated
using (auth.uid() = user_id);
```

Do not add broad insert/update policies unless the frontend starts writing directly to Supabase. Current insert path should remain backend-only because generation output and storage paths are produced server-side.

## Recommended Storage Policies

If the bucket remains public, clients can read images by URL and backend service role handles writes/deletes. If direct authenticated uploads are added later, constrain object paths to the authenticated user's folder.

```sql
create policy "Users can read generated images"
on storage.objects
for select
to authenticated
using (bucket_id = 'generated_images');
```

Optional stricter policy for non-public bucket designs:

```sql
create policy "Users can read own generated image objects"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'generated_images'
  and (storage.foldername(name))[1] = auth.uid()::text
);
```

## Data Lifecycle

1. User submits prompt and optional reference images.
2. Backend generates image through the local GLM-Image server.
3. Backend uploads PNG to `generated_images`.
4. Backend inserts a `public.generations` row.
5. Frontend displays `public_url` and history sorted by `created_at desc`.
6. Delete removes the storage object first, then deletes the database row.

## Notes And Gaps

- Reference images are request-only and are not stored in the database.
- Generation settings (`num_inference_steps`, `guidance_scale`) are not persisted in `public.generations`.
- Active/queued generation state is in backend memory only and is not stored in Supabase.
- No local migration files exist in this repository, so live constraints, indexes, and policies should be verified in the Supabase dashboard or with `supabase db pull`.
- `DELETE /api/history/{id}` deletes by generation ID only; it does not verify the row belongs to the requesting user. This is safe only if the backend route is otherwise protected or trusted. Consider changing the API to require `user_id` ownership validation before deletion.
