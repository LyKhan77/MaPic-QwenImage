#!/bin/bash

# Function to clean up background processes on exit
cleanup() {
    echo ""
    echo "Stopping MaPic services..."
    kill $(jobs -p) 2>/dev/null
    wait $(jobs -p) 2>/dev/null
    echo "Services stopped."
    exit 0
}

# Trap SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM

echo "Starting MaPic..."

# PyTorch memory optimization: reduce fragmentation that leads to OOM
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb:128

# Start GLM-Image Server
echo "Starting GLM-Image Server on port 30000..."
cd glm_image_server
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi
python -m uvicorn main:app --host 0.0.0.0 --port 30000 &
cd ..

# Start Backend
echo "Starting Backend on port 8181..."
cd backend
# Check if virtual environment exists, if not, warn user
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi
python -m uvicorn main:app --host 0.0.0.0 --port 8181 --reload &
cd ..

# Start Frontend
echo "Starting Frontend on port 5151..."
cd frontend
npm run dev &
cd ..

echo "MaPic is running!"
echo "- Frontend:     http://localhost:5151"
echo "- Backend:      http://localhost:8181"
echo "- GLM-Image:    http://localhost:30000"
echo "Press Ctrl+C to stop all services."

# Wait for all background processes
wait
