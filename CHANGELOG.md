# Changelog

Catatan perubahan MaPic. Format mengikuti [Conventional Commits](https://www.conventionalcommits.org/);
setiap entri memuat konteks, daftar berkas yang berubah, bukti, dampak, dan cara rollback.

> Catatan: berkas ini dibuat pada 2026-09-23. Commit-commit sebelumnya belum punya entri.

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
