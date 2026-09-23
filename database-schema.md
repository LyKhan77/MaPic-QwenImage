# MaPic Database Schema

Last reviewed: **2026-09-23** — kali ini lewat introspeksi langsung ke database live.

Dokumen ini menjelaskan skema Supabase yang dipakai MaPic. Isinya diverifikasi dengan membaca spesifikasi OpenAPI PostgREST (`GET {SUPABASE_URL}/rest/v1/` memakai service role key), sehingga mencerminkan kolom yang **benar-benar ada**, bukan hanya yang diasumsikan dari kode.

```bash
# Cara memverifikasi ulang
cd backend && source .venv/bin/activate
python - <<'PY'
import json, os, urllib.request
from dotenv import load_dotenv
load_dotenv(".env")
url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
req = urllib.request.Request(f"{url}/rest/v1/", headers={"apikey": key, "Authorization": f"Bearer {key}"})
spec = json.load(urllib.request.urlopen(req))
for table, schema in spec["definitions"].items():
    print(table, {c: m.get("format", m.get("type")) for c, m in schema["properties"].items()})
PY
```

## Supabase Products Used

| Product | Usage |
| --- | --- |
| Auth | Login/sesi frontend lewat Supabase Auth (Google OAuth). Saat review: 4 user terdaftar. |
| Postgres | Menyimpan riwayat generasi di `public.generations`. Saat review: 16 baris. |
| Storage | PNG hasil generasi di bucket `generated_images`. Bucket `generated_videos` masih ada sebagai sisa fitur video, tidak dipakai kode saat ini. |

## Auth Model

MaPic uses Supabase Auth as the identity source. The frontend reads the authenticated session and sends `session.user.id` to the backend as `user_id`.

The backend uses `SUPABASE_SERVICE_ROLE_KEY` for database and storage operations, so API-level authorization is enforced by backend route behavior rather than by the browser calling PostgREST directly.

## Tables

### `public.generations`

Stores one row per completed image generation.

| Column | Type | Nullable (live) | Source / Purpose |
| --- | --- | --- | --- |
| `id` | `uuid` | No | Generation record ID returned by API and used for deletion. |
| `user_id` | `uuid` | No | Owner user ID from Supabase Auth (`auth.users.id`). |
| `prompt` | `text` | No | User prompt. Backend validates request prompt length `1..2000`. |
| `image_path` | `text` | No | Internal Supabase Storage object path, format: `{user_id}/{uuid}.png`. |
| `public_url` | `text` | No | Public CDN URL returned by Supabase Storage. |
| `created_at` | `timestamptz` | **Ya** | Used for history sorting, newest first. Live DB tidak memasang constraint NOT NULL — semua 16 baris terisi, tetapi kolomnya sendiri nullable. |
| `media_type` | `text` | Ya | **Kolom warisan** dari fitur video. Seluruh baris berisi `image`. Tidak ada satu pun kode aplikasi yang membaca atau menulisnya (jalur insert di `supabase_service.py` hanya mengirim `user_id, prompt, image_path, public_url`). Aman dibiarkan; jangan dijadikan acuan jenis media — jenisnya ditentukan ekstensi di `image_path`. |

### DDL (mengikuti skema live)

```sql
create extension if not exists "pgcrypto";

create table if not exists public.generations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  prompt text not null check (char_length(prompt) between 1 and 2000),
  image_path text not null,
  public_url text not null,
  created_at timestamptz default now(),   -- nullable di DB live
  media_type text                          -- warisan fitur video, tidak dipakai kode
);

create index if not exists generations_user_created_at_idx
  on public.generations (user_id, created_at desc);
```

Bila membuat ulang dari nol, kolom `media_type` boleh dihilangkan — tidak ada konsumen yang membutuhkannya.

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
| Public access | `true` (terverifikasi) — diperlukan karena `public_url` ditampilkan, diunduh, dan disalin dari frontend. |

### Bucket: `generated_videos` (warisan)

Masih ada dan publik, tetapi tidak ada kode MaPic saat ini yang menulis ke sana. Kandidat penghapusan bila tidak ada rencana fitur video.

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
2. Backend meminta gambar ke facade, yang menjalankannya lewat ComfyUI + Qwen-Image 2.1 GGUF di GPU.
3. Backend uploads PNG to `generated_images`.
4. Backend inserts a `public.generations` row.
5. Frontend displays `public_url` and history sorted by `created_at desc`.
6. Delete removes the storage object first, then deletes the database row.

## Notes And Gaps

- Reference images are request-only and are not stored in the database.
- Generation settings (`num_inference_steps`, `true_cfg_scale`) are not persisted in `public.generations`.
- Active/queued generation state is in backend memory only and is not stored in Supabase.
- Kolom `created_at` nullable di DB walau semua baris terisi; constraint NOT NULL tidak dipasang. Index `generations_user_created_at_idx` **tidak bisa diverifikasi** lewat PostgREST — cek di dashboard Supabase (Database → Indexes) bila perlu.
- Kebijakan RLS juga tidak terbaca lewat PostgREST karena service role melewatinya. Bagian "Recommended RLS Policies" di bawah adalah usulan, belum tentu yang terpasang.
- `DELETE /api/history/{id}` deletes by generation ID only; it does not verify the row belongs to the requesting user. This is safe only if the backend route is otherwise protected or trusted. Consider changing the API to require `user_id` ownership validation before deletion.
