# Changelog

Catatan perubahan MaPic. Format mengikuti [Conventional Commits](https://www.conventionalcommits.org/);
setiap entri memuat konteks, daftar berkas yang berubah, bukti, dampak, dan cara rollback.

> Catatan: berkas ini dibuat pada 2026-09-23. Commit-commit sebelumnya belum punya entri.

---

## 2026-09-25 — `fix: keep remove-background mode across prompt input views`

**Konteks.** Verifikasi browser nyata menemukan cacat pada toggle Remove Background. `PromptInput` dipasang dua tempat yang saling menggantikan di `Dashboard.tsx`: instans terpusat di dalam `ImageCanvas` (tampil selama belum ada `currentGen`) dan bar bawah (tampil begitu `currentGen` ada). State `removeBg` hidup di `PromptInput`, jadi berpindah tampilan mengembalikannya ke `false` diam-diam. Reproduksi: nyalakan toggle di input terpusat → klik satu item riwayat → bar bawah terpasang dengan `removeBg=false` (`aria-pressed="false"`), lalu tombol kirim menembak `/api/generate` bukan `/api/remove-background`. Ini melanggar alur yang disetujui: nyalakan Remove Background → pilih sumber dari riwayat atau unggah → kirim.

**Yang berubah.**

| Berkas | Perubahan |
|---|---|
| `frontend/src/pages/Dashboard.tsx` | State `removeBg` (default `false`) pindah ke sini dan diteruskan sebagai pasangan prop terkontrol (`removeBg`, `onRemoveBgChange`) ke **kedua** jalur pemasangan `PromptInput` — lewat `<ImageCanvas>` dan bar bawah. `handleNewChat` juga `setRemoveBg(false)` supaya obrolan baru tidak mewarisi mode cutout; muat ulang halaman tetap `false` karena nilai awalnya `false`. Tidak ada perubahan lain pada handler generate/cutout, `hasCurrentUserGenerationWork`, atau pemilihan riwayat. |
| `frontend/src/components/ImageCanvas.tsx` | Prop `removeBg`/`onRemoveBgChange` ditambahkan ke `ImageCanvasProps` dan diteruskan apa adanya ke `PromptInput` terpusat, sejajar dengan `onGenerate`/`onRemoveBackground` yang sudah ada. Tidak ada perubahan tampilan atau logika kanvas. |
| `frontend/src/components/PromptInput.tsx` | `useState` lokal `removeBg` dihapus; nilainya kini datang dari prop. `toggleRemoveBg` memanggil `onRemoveBgChange(!removeBg)` lalu menutup modal Settings seperti sebelumnya. Tombol gunting tidak disentuh: `type="button"`, `aria-label="Remove Background"`, `aria-pressed={removeBg}`, kelas `h-11 w-11`/`min-h-11 min-w-11`, `title` sama persis. Perilaku lokal lain utuh: input teks disabled saat cutout, penyembunyian Settings dan portal, banner model sleeping, batas 1 gambar + pesannya, latch submit, penjaga `isReadingFiles`, penjaga versi prefill riwayat. |
| `frontend/scripts/check-remove-background-ui.mjs` | Tambah penjaga regresi berbasis pembacaan sumber (pola `check-active-generation-state.mjs`): `PromptInput` tidak boleh punya `[removeBg, setRemoveBg]`, wajib mendeklarasikan kedua prop, wajib memanggil `onRemoveBgChange(!removeBg)`; `Dashboard` wajib punya `useState(false)`, mengirim pasangan prop itu tepat dua kali ke `PromptInput` dan sekali ke `ImageCanvas`, serta mereset `setRemoveBg(false)` di `handleNewChat`. Tanpa dependensi baru. |
| `CHANGELOG.md` | Entri ini. |

**Bukti.**

- `npm --prefix frontend run check:remove-background` → empat keluaran lama tetap (`stripDataUrlPrefix OK`, `canSubmitRemoveBackground 4 outcomes OK`, `isCutoutGeneration exact-label-only OK`, `removeBackgroundSendLabel busy/idle OK`) plus `removeBg owned by Dashboard, forwarded to both inputs OK`.
- `npm --prefix frontend run build` → `✓ 2220 modules transformed.` `dist/assets/index-D1GHOhN_.css 39.39 kB` `dist/assets/index-DXmfOvhv.js 621.54 kB` `✓ built in 1.42s` (hanya peringatan chunk >500 kB yang sudah lama ada).
- `npm --prefix frontend run lint` → `✖ 5 problems (5 errors, 0 warnings)` — sama persis dengan jumlah di commit sebelumnya; kelimanya pra-eksisting (`BearAnimation.tsx:27`, `GenerationStageBadge.tsx:25`/`:26`, `useGenerationStatus.ts:25`, `Login.tsx:45`) dan tidak ada di berkas yang disentuh commit ini.
- `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=test backend/.venv/bin/python -m unittest discover -s backend/tests` → `Ran 33 tests in 0.204s` `OK`.
- `git diff --check` bersih.
- Jejak statis (dibaca dari kode final, bukan diklaim sebagai bukti browser): saat `removeBg === true` dan tampilan berpindah dari input terpusat ke bar bawah, `currentGen` menjadi non-null sehingga cabang `{currentGen && (...)}` di `Dashboard.tsx` memasang `PromptInput` bar bawah dengan `removeBg={removeBg}` — nilai state Dashboard yang sama, bukan state komponen yang baru lahir. Karena itu `aria-pressed` bar bawah ikut `true` dan submit memakai jalur `onRemoveBackground`. Gambar sumber tidak hilang karena ia di-prefill lewat `initialImageUrl` dari `currentGen.public_url` seperti sebelumnya. Verifikasi browser nyata dijalankan controller **setelah** commit ini; tidak diklaim di sini.

**Dampak.** Perilaku berubah hanya pada satu kasus: mode cutout kini bertahan saat pengguna memilih sumber dari riwayat, sehingga alur nyalakan-toggle → pilih sumber → kirim berjalan sesuai rancangan. Saat toggle mati tidak ada perubahan. Tidak ada perubahan skema DB, Docker, backend, atau berkas di luar empat berkas frontend di atas; tidak ada konteks/provider baru.

**Rollback.** `git revert <sha>` mengembalikan `removeBg` sebagai state lokal `PromptInput` beserta hilangnya penjaga regresi di skrip cek; tidak ada migrasi data atau artefak runtime yang perlu dibersihkan.

---

## 2026-09-25 — `feat: add remove background toggle to prompt input`

**Konteks.** Langkah ketiga fitur Remove Background: satu toggle gunting di baris input yang mengubah Generate (Qwen) menjadi Remove Background (CPU). Satu tombol, bukan menu tiga mode; tidak ada Image Edit maupun masking. Toggle harus hidup saat model Qwen `unloaded` karena endpoint cutout tidak menyentuh ComfyUI. Sumber cutout tetap ada di riwayat setelah diproses: hasilnya record baru, bukan penimpa. Bobot model belum di-mount di container (Task 4), jadi di host endpoint masih 503 — UI sendiri sudah mengirim request yang benar.

**Yang berubah.**

| Berkas | Perubahan |
|---|---|
| `frontend/src/lib/removeBackground.ts` | Baru. Helper murni tanpa React: `REMOVE_BACKGROUND_LABEL`, `stripDataUrlPrefix`, `canSubmitRemoveBackground` (alasan `no-image`/`too-many`/`reading`, `reading` menang agar hanya satu pesan tampil), `removeBackgroundSendLabel`, `isCutoutGeneration`. |
| `frontend/src/lib/api.ts` | Tambah `api.removeBackground(image)` — `authHeaders(true)`, `POST /remove-background`, body `{ image }`, `detail` backend diangkat ke `Error.message` dengan pola sama seperti `generateImage`. `generateImage` dan alur token tidak disentuh. |
| `frontend/src/components/PromptInput.tsx` | State `removeBg` (default `false`) + tombol gunting (`type="button"`, `aria-label="Remove Background"`, `aria-pressed`, `title` deskriptif) tepat sebelum `Settings2`; aktif = `bg-primary` + cincin `inset` + `aria-pressed`, jadi terlihat tanpa hover dan tidak hanya warna. Saat on: input teks disabled dengan placeholder "No prompt needed", tombol Settings disembunyikan, portal modal dijaga `!removeBg`, banner "model sleeping" disembunyikan, lampiran dibatasi 1 (pilih >1 file → hanya file pertama, tanpa membuang lampiran lama), pesan instruksi saat 0 atau >1 gambar, label kirim `REMOVE BG`/`REMOVING...`. Submit cutout memanggil `onRemoveBackground(base64 tanpa prefix)` di bawah latch `useRef` dan tidak mengosongkan lampiran (sumber tetap tampil saat gagal). Saat off: perilaku lama utuh (prompt wajib, sampai 10 referensi, Enter, `GENERATE`). Perbaikan bug: efek `initialImageUrl` kini memakai penjaga versi (`prefillRequestRef` + `manualSelectionVersionRef`) sehingga fetch riwayat yang telat tidak menimpa gambar yang baru dilampirkan pengguna. Thumbnail hapus juga selalu terlihat saat toggle on agar pengguna bisa mengurangi ke satu gambar di layar sentuh. |
| `frontend/src/pages/Dashboard.tsx` | Tambah `isRemovingBackground` + `handleRemoveBackground(imageBase64)`, terpisah dari `handleGenerate`: tanpa entri `pendingGenerations`, tanpa `pendingGenParams`/stage/step Qwen, tanpa `MAX_GLOBAL_GENERATIONS`. Sukses → `Generation` baru masuk ke depan cache `['history', session.user.id]`, `setCurrentGen`, toast. Gagal → toast pesan dari `detail` backend, tampilan tetap bisa dipakai. Handler diteruskan ke kedua pemakaian `<PromptInput>` (`ImageCanvas` terpusat dan bar bawah). Filter riwayat `selectGeneratedPngHistory` tidak diubah: hasil cutout PNG. |
| `frontend/src/components/ImageCanvas.tsx` | Prop `isRemovingBackground`/`onRemoveBackground`. Selama cutout berjalan tampil loader dengan teks "Removing background..." (tanpa stage/step Qwen). Hasil cutout dideteksi murni dari label server lewat `isCutoutGeneration` dan digambar di atas latar kotak-kotak `repeating-conic-gradient`; komentar mencatat batas kosmetiknya (prompt Create buatan pengguna dengan teks persis sama ikut terkena). Tata letak, jarak, tombol unduh/salin tidak berubah. |
| `frontend/scripts/check-remove-background-ui.mjs` | Baru. Cek Node polos + `assert` (gaya `check-active-generation-state.mjs`): strip prefix (PNG/JPEG/tanpa prefix/string kosong), empat hasil `canSubmitRemoveBackground`, `isCutoutGeneration` hanya benar untuk label persis (beda huruf besar, spasi tambahan, `undefined`, `null`, string kosong), label kirim busy/idle. |
| `frontend/package.json` | Tambah satu skrip `check:remove-background`. Tanpa dependensi baru. |

**Bukti.**

- `npm --prefix frontend run check:remove-background` → `removeBackground: stripDataUrlPrefix OK` / `canSubmitRemoveBackground 4 outcomes OK` / `isCutoutGeneration exact-label-only OK` / `removeBackgroundSendLabel busy/idle OK`.
- `npm --prefix frontend run build` → `✓ 2220 modules transformed.` `dist/assets/index-D1GHOhN_.css 39.39 kB` `dist/assets/index-ViG84PBD.js 621.36 kB` `✓ built in 1.50s` (hanya peringatan chunk >500 kB yang sudah lama ada).
- `npm --prefix frontend run lint` → `✖ 5 problems (5 errors, 0 warnings)`. Baseline HEAD diukur ulang di worktree bersih: `✖ 8 problems (8 errors, 0 warnings)`. Jadi commit ini **menghapus 3 error lama**, tidak menambah: `PromptInput.tsx:40` (`initialPrompt` di effect) dan `Dashboard.tsx:95`/`:144` (setState di effect) sudah tidak ada setelah restrukturisasi. Sisa 5 error sepenuhnya pra-eksisting: `BearAnimation.tsx:27`, `GenerationStageBadge.tsx:25`/`:26`, `useGenerationStatus.ts:25`, `Login.tsx:45`. Tidak ada error di berkas yang disentuh commit ini.
- `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=test backend/.venv/bin/python -m unittest discover -s backend/tests` → `Ran 33 tests in 0.201s` `OK`.
- `git diff --check` bersih. Belum ada verifikasi browser nyata pada commit ini (klik toggle, request tunggal, checkerboard, 320/390px) — itu dijalankan controller setelah ini, bukan diklaim di sini.

**Dampak.** Tombol baru muncul di kedua baris input. Saat off tidak ada perubahan perilaku. Saat on, Generate tidak bisa dijalankan sampai toggle dimatikan, dan Settings Qwen disembunyikan. Satu cutout berjalan pada satu waktu (429 dari backend bila sibuk). Tidak ada perubahan skema DB, Docker, atau berkas backend. Selama bobot ONNX belum di-mount (Task 4), menekan kirim cutout menghasilkan toast error 503 dari backend; tampilan tetap bisa dipakai.

**Rollback.** `git revert <sha>` menghapus toggle, handler, helper, skrip cek, dan entri ini; tidak ada migrasi data atau artefak runtime yang perlu dibersihkan.

---

## 2026-09-25 — `feat: add remove-background endpoint`

**Konteks.** Langkah kedua fitur Remove Background: endpoint HTTP yang menyambungkan worker CPU (Task 1) ke riwayat pengguna. Endpoint harus mandiri dari jalur Qwen — tidak memakai slot antrean, tidak memakai `_generation_lock`, tidak butuh model Qwen termuat — serta menolak input mahal sebelum inferensi. Batas angka, urutan validasi, dan pemetaan status mengikuti `docs/superpowers/specs/2026-09-25-remove-background-isnet-design.md`. Belum ada UI (Task 3) dan belum ada mount bobot di container (Task 4), jadi endpoint ini belum bisa menghasilkan cutout di host mana pun tanpa bobot lokal.

**Yang berubah.**

| Berkas | Perubahan |
|---|---|
| `backend/schemas.py` | Tambah `RemoveBackgroundRequest(image: str)`. Tidak ada field `user_id`: identitas tetap dari token. |
| `backend/main.py` | Tambah `POST /api/remove-background` (`Depends(require_user)`, `response_model=Generation`). Urutan penjagaan: auth → `len(image) > 2_800_000` karakter → `base64.b64decode(validate=True)` → `len(raw) > 2 MiB` → Pillow `open`/`load` → `format in {PNG, JPEG}` → `width/height <= 0`, sisi > 2048, atau piksel > 4_194_304 → lock → inferensi. Pemetaan kegagalan: 413 (2×), 422 (4×), 429 (worker sibuk), 503 (`ModelUnavailableError`), 502 (`RemoveBackgroundError`), 502 (Supabase). Pesan 503 sengaja dirampat karena pesan worker memuat path bobot lokal; kekecualiannya dicatat `logger.exception` di server. Sukses: `await asyncio.to_thread(remove_background_service.remove_background_png, raw)` → `upload_image` → `insert_generation(user_id, "Remove background", …)`. Lock baru `_remove_background_lock` (satu slot, komentar `ponytail:` menjelaskan batas ~3 GiB sesi) diperiksa `locked()` sebelum `async with` supaya permintaan kedua dapat 429, bukan ikut mengantre. `_remove_background_lock` tidak pernah disentuh `/api/generate`, dan endpoint ini tidak menyentuh `_active_generations`/`MAX_GLOBAL_GENERATIONS`. |
| `backend/services/supabase_service.py` | Tambah `delete_stored_image(image_path) -> None` — best-effort `storage.remove([path])`, hanya gagal dicatat `logger.exception`. Dipakai endpoint ini **hanya** saat insert gagal setelah upload sukses, sehingga tidak ada berkas yatim di bucket. Sumber asli tidak pernah dihapus: endpoint ini tidak menyimpannya sama sekali. |
| `backend/tests/test_remove_background.py` | Tambah 21 tes endpoint (total 31 di berkas ini) dengan `TestClient`, override `require_user`, dan `unittest.mock.patch` pada `backend.main.upload_image`, `backend.main.insert_generation`, `backend.main.delete_stored_image`, serta `remove_background_service.remove_background_png` — tanpa inferensi, jaringan, atau database. Cakupan: 401 tanpa header dan dengan token palsu (tanpa override), 413 (string base64 terlalu panjang, byte hasil dekode > 2 MiB), 422 (base64 rusak, payload bukan gambar, BMP, GIF, PNG ber-IHDR 0×0, sisi 2049, piksel 2048×2049), 503, 502 worker, 502 insert (+ `delete_stored_image` dipanggil tepat sekali dengan path hasil upload), 502 upload (cleanup tidak dipanggil, insert tidak dipanggil), 200 dengan label `Remove background` dan byte tersimpan benar-benar PNG RGBA, 200 saat `generate_image_bytes` dipatch melempar `AssertionError` dan `get_health_status` mengembalikan `unloaded` (jalur Qwen tidak tersentuh), `_generation_lock` tetap terbuka setelah sukses, 429 saat lock dipakai. Tes 429 memakai `threading.Event` (worker pertama menahan, worker kedua dicek dari thread utama), bukan polling `time.sleep`. `TestClient` dibuat sekali di `setUpModule` karena `asyncio.Lock` modul terikat ke satu event loop. |
| `CHANGELOG.md` | Entri ini. |

**Bukti.** `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=test backend/.venv/bin/python -m unittest backend.tests.test_remove_background -v` → `Ran 31 tests ... OK`. `... -m unittest discover -s backend/tests -v` → `Ran 33 tests ... OK` (2 tes kapasitas lama tetap lulus). `backend/.venv/bin/python -m compileall -q backend` tanpa keluaran. `git diff --check` bersih. Tes RED dijalankan lebih dulu dan gagal karena route belum ada (`404 != 413`, `404 != 502`, `404 != 422`, `404 != 200`, `AttributeError: backend.main has no attribute 'delete_stored_image'`; 18 failure + 2 error) sebelum implementasi. Mutasi penjaga 429 (blok `locked()` dihapus sementara) membuat `test_busy_worker_is_429_without_queuing` gagal `200 != 429`, jadi penjaga itu memang yang diuji. Tes lulus tanpa `rembg` di `backend/.venv` dan tanpa jaringan; belum ada uji GPU, host, bobot nyata, mutu alpha, atau UI.

**Dampak.** Endpoint baru belum dipakai UI, jadi perilaku aplikasi bagi pengguna belum berubah. `/api/generate`, auth, skema DB, Docker, dan frontend tidak disentuh. Satu permintaan cutout pada satu waktu per proses backend; permintaan bersamaan menerima 429 dan tidak mengantre. Belum ada penjagaan laju per pengguna — ponytail: tambahkan bila penyalahgunaan terbukti.

**Rollback.** `git revert <sha>` menghapus endpoint, model request, helper cleanup, dan tesnya; tidak ada migrasi data, tabel, atau artefak runtime yang perlu dibersihkan.

---

## 2026-09-25 — `feat: add CPU background removal worker`

**Konteks.** Langkah pertama fitur Remove Background: worker inferensi lokal yang mengubah satu gambar menjadi PNG transparan baru. Inferensi tidak boleh menyentuh Qwen/ComfyUI dan tidak boleh mengunduh bobot diam-diam; endpoint HTTP, UI, serta mount volume bobot dikerjakan di task terpisah. Hasil pilot CPU (`isnet-general-use`, md5 `fc16ebd8b0c10d971d3513d564d01e29`) dipakai sebagai dasar ukuran dan waktu, bukan sebagai klaim mutu.

**Yang berubah.**

| Berkas | Perubahan |
|---|---|
| `backend/services/remove_background_service.py` | Baru. `MODEL_NAME = "isnet-general-use"`, `RemoveBackgroundError`, `ModelUnavailableError`, `remove_background_png(source: bytes) -> bytes`. Alur: Pillow buka → `ImageOps.exif_transpose` → `RGBA` → encode PNG → sesi `rembg` (satu per proses) → hasil dibuka `RGBA` → tolak ukuran berbeda → alpha = `ImageChops.darker(alpha sumber, alpha model)`, RGB diambil dari sumber → PNG lewat `BytesIO`. `rembg` diimpor di dalam `_session_factory`/`_extract` sehingga import modul tidak memicu unduhan. Sebelum sesi dibangun, keberadaan berkas bobot dicek di `REMBG_HOME` / `XDG_DATA_HOME/rembg` / `~/.rembg` (bentuk `models/<nama>/<nama>.onnx` atau bentuk lama `<home>/<nama>.onnx`); bila tidak ada, `ModelUnavailableError` dilempar tanpa percobaan jaringan. Checksum tidak pernah dinonaktifkan. |
| `backend/tests/test_remove_background.py` | Baru. 7 tes `unittest` dengan `mock.patch` pada `_session_factory` dan `_extract`: mode/ukuran/tanda tangan PNG, RGB dari sumber, irisan alpha (sudut transparan tetap 0, alpha model 0 dan 120 dipertahankan), normalisasi EXIF orientation 6, bobot hilang → `ModelUnavailableError` tanpa membangun sesi, ukuran hasil berbeda → `RemoveBackgroundError`, sesi dipakai ulang lintas panggilan. |
| `backend/requirements.txt` | Tambah `rembg[cpu]==2.0.85` (ONNX Runtime CPU, tanpa torch). |

**Bukti.** `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=test backend/.venv/bin/python -m unittest backend.tests.test_remove_background -v` → `Ran 7 tests ... OK`. `... -m unittest discover -s backend/tests -v` → `Ran 9 tests ... OK` (2 tes kapasitas lama tetap lulus). `backend/.venv/bin/python -m compileall -q backend` tanpa keluaran. Tes lulus tanpa `rembg` terpasang di `backend/.venv` dan tanpa jaringan. Berkas tes di-`git add -f` karena aturan ignore generik `tests/` (`.gitignore:34`); `git ls-files --error-unmatch backend/tests/test_remove_background.py` mencetak path-nya. Belum ada uji GPU, host, atau gambaran mutu pada commit ini.

**Dampak.** Belum ada perubahan perilaku aplikasi: worker belum dipanggil endpoint mana pun. `backend/requirements.txt` menambah dependensi besar (~461 MB venv pada pilot), jadi rebuild image backend berikutnya memuat ONNX Runtime. Tidak ada perubahan skema DB, auth, Docker, atau frontend.

**Rollback.** `git revert <sha>` menghapus worker, tes, dan entri requirements; tidak ada migrasi data atau artefak runtime yang perlu dibersihkan.

**Perbaikan review.** Tiga temuan diperbaiki di `backend/services/remove_background_service.py`. Pertama, penjaga bobot tidak lagi menebak lokasi berkas: `_model_path()` memakai resolver rembg sendiri (`DisSession.resolve_existing`) bila rembg terpasang, dan jatuh ke `_fallback_model_path()` yang meniru `rembg_home()`/`legacy_home()`/`resolve_existing()` persis (prioritas `U2NET_HOME`, lalu `REMBG_HOME`, lalu `XDG_DATA_HOME/rembg`, lalu `~/.rembg`; kandidat kedua `<legacy_home>/<nama>.onnx`). Sebelumnya guard menerima `<REMBG_HOME>/<nama>.onnx` yang tak pernah dibaca rembg, jadi pemeriksaan bisa lulus sementara rembg mengunduh ~170 MB. Kandidat yang dicari kini ikut dicetak di pesan `ModelUnavailableError`. Kedua, pembuatan sesi dijaga `threading.Lock` dengan double-checked locking karena `remove_background_png` akan dipanggil lewat `asyncio.to_thread` dan dua pemanggil bisa membangun dua sesi ~3 GiB. Ketiga, hasil model wajib membawa kanal alpha (`"A" not in cutout.getbands()` → `RemoveBackgroundError`); keluaran 3 kanal tadinya menjadi alpha 255 di seluruh gambar dan tampak seperti cutout sempurna. Sekalian: `normalised.copy()` dihapus (`putalpha` pada citra privat itu aman) dan `_session_factory`/`_extract` diberi anotasi. Tes bertambah 3 (10 total di berkas ini): orientasi EXIF diperiksa lewat piksel dengan sumber asimetris 3x2 (ukuran `(2, 3)` saja tidak membedakan rotate 90/270 dengan TRANSPOSE), `test_import_does_not_load_rembg` memastikan `rembg` tetap absen dari `sys.modules` setelah modul dimuat ulang, `test_cutout_without_alpha_is_rejected`, dan `test_concurrent_callers_build_one_session` (gagal `8 != 1` tanpa lock). Tes bobot-hilang sekarang juga memastikan direktori temp tetap kosong dan `MODEL_CHECKSUM_DISABLED` tidak diset.

**Bukti (perbaikan review).** `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_ROLE_KEY=test backend/.venv/bin/python -m unittest backend.tests.test_remove_background -v` → `Ran 10 tests ... OK`. `... -m unittest discover -s backend/tests -v` → `Ran 12 tests ... OK`. `backend/.venv/bin/python -m compileall -q backend` tanpa keluaran. Guard diuji terhadap rembg 2.0.85 sungguhan di `/tmp/rembg-probe-venv`: dengan `REMBG_HOME=/tmp/rembg-probe-data`, `_model_path()` mengembalikan `/tmp/rembg-probe-data/models/isnet-general-use/isnet-general-use.onnx`, sama dengan `DisSession.resolve_existing("isnet-general-use.onnx")`.

---

## 2026-09-24 — `chore: abaikan spesifikasi dan rencana desain lokal`

**Konteks.** Spesifikasi serta rencana kerja ialah catatan lokal, bukan dokumen yang dikomit. Commit rancangan sebelumnya keliru melacak satu spesifikasi.

**Yang berubah.** `.gitignore` mengabaikan `docs/plans/`, `docs/superpowers/plans/`, `docs/superpowers/specs/`, dan `.cooper/context/`. Spesifikasi yang terlanjur masuk commit dikeluarkan dari tracking tanpa menghapus file lokal.

**Bukti.** `git check-ignore -v` untuk plans/specs/checkpoint; `git ls-files` memastikan tak ada spec/plan terlacak. Belum ada kode fitur atau uji GPU.

**Dampak.** Hanya aturan tracking Git berubah; perilaku aplikasi, skema, dan deployment tetap.

**Rollback.** `git revert <sha>` mengembalikan aturan ignore; tidak ada migrasi data.

---

## 2026-09-23 — `fix(frontend): layout responsif mobile + drawer sidebar`

**Konteks.** Layout web app desktop-only. Audit Playwright pada viewport 390px menemukan
bug yang mematikan fungsi, bukan sekadar kosmetik: badge status model (`absolute top-4 right-6`,
lebar 325px) meluber keluar kolom `main` dan menimpa sidebar, sehingga tombol toggle sidebar
24×24 tidak bisa diklik — dibuktikan Playwright dengan
`<span ...>Model</span> ... intercepts pointer events`. Akibatnya, sekali sidebar dibuka di
ponsel (256px dari 390px), kolom `main` tinggal 134px dan tombol settings (`x=554`) serta
send (`x=602`) berada di luar viewport: generasi mustahil dijalankan **dan** sidebar tidak bisa
ditutup. Selain itu, nol utility breakpoint Tailwind di seluruh `src/`.

**Yang berubah.**

| Berkas | Perubahan |
|---|---|
| `frontend/src/components/Sidebar.tsx` | Sidebar jadi overlay drawer (280px, slide-in) di bawah 768px, dibuka lewat hamburger 44×44, ditutup lewat tombol X / tap backdrop / pilih riwayat / New Generation. Backdrop `z-[55]`, drawer `z-[60]`. Rail collapsed 80px kini khusus desktop. State mobile dibaca lewat `matchMedia`. |
| `frontend/src/pages/Dashboard.tsx` | `h-screen` → `h-dvh`; badge stack `top-4 right-6` → `right-4 top-16 md:right-6 md:top-4` agar tidak bertabrakan dengan hamburger. |
| `frontend/src/components/ImageCanvas.tsx` | Padding `p-8` → `p-3 md:p-8`; overlay unduh/salin tidak lagi hover-only; `pt-20` → `pt-28 md:pt-20`; tombol overlay `p-2` → `p-3 md:p-2`. |
| `frontend/src/components/PromptInput.tsx` | Prompt bar `p-6` → `p-3` + `env(safe-area-inset-bottom)`; hint "ENTER to send" desktop-only; label tombol GENERATE disembunyikan di bawah `sm`; tombol ikon `h-10 w-10` → `h-11 w-11`; input dapat `min-w-0`; `enterKeyHint="send"`. |
| `frontend/src/components/ModelStatusBadge.tsx` | Label "Model" + bar progres dibungkus `hidden sm:contents` → lebar badge 325px menjadi 163px; tombol Retry dapat area sentuh 61×47px lewat pseudo-element. |
| `frontend/src/components/ActiveGenerationsIndicator.tsx` | `bottom-4` → `bottom-24 md:bottom-4`; panel daftar bisa dibuka dengan tap. |
| `frontend/src/pages/Login.tsx` | `min-h-screen` → `min-h-dvh`; tombol mata `p-1` → `p-3`; tautan "Forgot?" dan "Need new credentials" dapat area sentuh pseudo-element. |
| `frontend/index.html` | `viewport-fit=cover`. |
| `frontend/src/index.css` | `min-height: 100dvh` setelah `100vh` (progressive enhancement). |
| `.gitignore` | Abaikan `.playwright-mcp/`. |

**Bukti.** `npx tsc -b` exit 0; `npx vite build` sukses (2219 modul). Layout sweep Chromium pada
320/390/430/768/1024/1440px: `overflowX` 0, tinggi root = viewport (`dvh` aktif), badge selalu di
dalam viewport, tidak ada tumpang tindih badge↔hamburger, `main` selebar viewport di mobile,
seluruh anak prompt bar berada di dalam pill. Suite interaksi 9 langkah lulus semua (hamburger,
X, tap backdrop, New Generation, toggle rail desktop, reset drawer saat resize, login @390).
Bukti mentah: `temp/mobile-audit-2026-09-23/`. Rancangan + tabel angka: `docs/superpowers/plans/2026-09-23-responsif-mobile.md`.

**Dampak.** Pengguna ponsel akhirnya bisa memakai app: konten selebar layar, riwayat terjangkau
lewat drawer, tombol generate terlihat. Desktop tidak berubah (768px ke atas identik). Target
sentuh ≥44px berlaku sampai breakpoint `lg`. Belum diuji di perangkat fisik — bukti gestur berasal
dari input tersintesis Chromium; `dvh` dan `env(safe-area-inset-*)` belum diverifikasi di Safari/iOS.

**Rollback.** `git revert <sha>`. Tidak ada perubahan skema, API, kontainer, atau data — hanya
kelas Tailwind dan satu komponen. Tidak perlu rebuild image untuk kembali ke perilaku lama selain
build ulang frontend.
