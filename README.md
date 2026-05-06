# MaPic - GenAI Image Studio

**Developed by Lee Khan** | *Synthesizing the Future*

MaPic turns text prompts and reference images into production-quality visuals — running entirely on local hardware. Built on **GLM-Image** (9B AR + 7B diffusion decoder), it delivers text-to-image and multi-reference image-to-image generation with no cloud dependencies, no API costs, and no rate limits.

## 🚀 Features

*   **AI Image Generation:** Generate images using GLM-Image (local inference via diffusers pipeline).
*   **Multi-Reference Support:** Attach up to 3 reference images for image-to-image generation (style transfer, editing, identity-preserving).
*   **Modern UI:** Futuristic "Glassmorphism" design with smooth animations (Framer Motion).
*   **Theme Support:** Fully supported **Dark** and **Light** modes with a one-click toggle.
*   **VRAM Optimization (Soft Unload):** Automatically unloads the model from GPU VRAM after 1 hour of inactivity to save resources. Supports manual **Load/Unload** directly from the UI status badge.
*   **On-Demand Loading:** Automatically reloads the model when a new generation request is made, ensuring a seamless experience even after the model has been idle.
*   **History Management:** Automatically saves generated images and prompts. View, select, and delete history items.
*   **Responsive Design:** Collapsible sidebar and mobile-friendly layout.
*   **Secure Auth:** Google OAuth 2.0 via Supabase Authentication.
*   **Share & Download:** Easily download images or copy direct links to the clipboard.

## 🏗️ Architecture

```
Frontend (React :5151)
    ↓
MaPic Backend (FastAPI :8181)
    ↓
GLM-Image Server (FastAPI :30000)
    ↓
diffusers GlmImagePipeline (3-GPU bf16, 56 GB VRAM)
```

## 🛠️ Tech Stack

### Frontend
*   **Framework:** React (Vite)
*   **Styling:** Tailwind CSS
*   **Icons:** Lucide React
*   **State Management:** TanStack Query (React Query)
*   **Animations:** Framer Motion
*   **Notifications:** Sonner

### Backend
*   **Framework:** Python FastAPI
*   **AI Engine:** GLM-Image (local diffusers pipeline)
*   **Database & Storage:** Supabase (PostgreSQL + Storage Buckets)

### Inference Server
*   **Framework:** Python FastAPI + Uvicorn
*   **Model:** GLM-Image (9B AR + 7B Diffusion Decoder)
*   **Runtime:** PyTorch with CUDA, diffusers, transformers

## 📦 Installation & Setup

### Prerequisites
*   Node.js & npm
*   Python 3.10+
*   CUDA-capable GPUs: 3x NVIDIA GPUs totaling ~56 GB VRAM (2x RTX 5080 16 GB + RTX 4090 24 GB)
*   Supabase Account (Project URL & Service Role Key)

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/mapic.git
cd mapic
```

### 2. GLM-Image Server Setup
```bash
cd glm_image_server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

First run downloads ~35GB model from HuggingFace. Start the server:
```bash
python -m glm_image_server.main
# Wait for "GLM-Image pipeline loaded." before testing
```

### 3. Backend Setup
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in `backend/`:
```env
SUPABASE_URL="your_supabase_url"
SUPABASE_SERVICE_ROLE_KEY="your_supabase_service_role_key"
GLM_IMAGE_API_URL="http://localhost:30000"
CORS_ORIGINS="http://localhost:5151"
```

### 4. Frontend Setup
```bash
cd frontend
npm install
```

Create a `.env` file in `frontend/`:
```env
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_ANON_KEY=your_supabase_anon_key
```

### 5. Run Everything

```bash
# From project root
bash start-app.sh
```

Or start services individually:
```bash
# Terminal 1: GLM-Image Server
cd glm_image_server && source .venv/bin/activate && python -m glm_image_server.main

# Terminal 2: Backend
cd backend && source venv/bin/activate && python -m uvicorn main:app --host 0.0.0.0 --port 8181 --reload

# Terminal 3: Frontend
cd frontend && npm run dev
```

- Frontend: http://localhost:5151
- Backend: http://localhost:8181
- GLM-Image Server: http://localhost:30000

## 🖼️ Usage

1.  Login with your Google account.
2.  Use the **Prompt Input** at the bottom to describe the image you want.
3.  Attach reference images (up to 3, max 2MB each) via the paperclip button.
4.  Click **Generate** or press Enter.
5.  View your creation in the main canvas.
6.  Use the **Sidebar** to access previous generations or switch themes.

## ⚡ Creator

Developed with vision by **Lee Khan**.
*The code is the canvas.*
