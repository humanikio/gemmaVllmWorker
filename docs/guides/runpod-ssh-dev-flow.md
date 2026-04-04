# RunPod CLI + SSH Dev Flow

How to spin up a GPU pod on RunPod, SSH in, and test the gemmaVllmWorker locally on real hardware.

## Prerequisites

- A RunPod account with credits
- Your RunPod API key (Settings > API Keys in the RunPod console)

## 1. Install runpodctl

```bash
# macOS (Homebrew)
brew install runpod/runpodctl/runpodctl

# Linux / WSL
wget -qO- cli.runpod.net | sudo bash
```

## 2. First-Time Setup

Run the interactive doctor command. It will configure your API key and generate an SSH key pair in one step:

```bash
runpodctl doctor
```

This does three things:
1. Saves your API key to `~/.runpod/config.toml`
2. Generates an SSH key pair at `~/.runpod/ssh/RunPod-Key-Go`
3. Uploads the public key to RunPod's cloud

You only need to do this once per machine.

### What gets created

| File | Purpose |
|------|---------|
| `~/.runpod/config.toml` | API key and CLI config |
| `~/.runpod/ssh/RunPod-Key-Go` | SSH private key (never share this) |
| `~/.runpod/ssh/RunPod-Key-Go.pub` | SSH public key (auto-uploaded to RunPod) |

## 3. Check Available GPUs

```bash
runpodctl gpu list --output=table
```

We target 24GB GPUs for this worker. Good options:

| GPU | VRAM | Approx. Cost |
|-----|------|-------------|
| NVIDIA L4 | 24 GB | ~$0.24/hr |
| NVIDIA RTX A5000 | 24 GB | ~$0.20/hr |
| NVIDIA GeForce RTX 4090 | 24 GB | ~$0.29/hr |
| NVIDIA GeForce RTX 3090 | 24 GB | ~$0.16/hr |

Note: RTX 3090 is Ampere (sm_86) and cheapest, but L4 is Ada (sm_89) and may have better vLLM attention backend support for Gemma 4's heterogeneous head dims. RTX 4090 is also Ada. Prefer L4 or RTX 4090 for best compatibility.

## 4. Create a GPU Pod

```bash
runpodctl pod create \
  --image runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04 \
  --gpu-id "NVIDIA L4" \
  --gpu-count 1 \
  --volume-in-gb 50 \
  --container-disk-in-gb 30 \
  --ports "22/tcp,8000/http"
```

Port 8000 is for the local test API server (optional). The command returns a pod ID.

## 5. SSH Into the Pod

```bash
# List your pods to get the ID
runpodctl pod list --output=table

# Get SSH connection command
runpodctl ssh info <pod-id>
```

This prints the full SSH command. It looks like:

```bash
ssh root@<ip> -p <port> -i ~/.runpod/ssh/RunPod-Key-Go
```

Copy-paste and connect.

## 6. Set Up the Worker on the Pod

Once SSH'd in:

```bash
# Clone the repo
cd /workspace
git clone <your-repo-url> gemmaVllmWorker
cd gemmaVllmWorker

# Install dependencies (vLLM + extras)
pip install "vllm[flashinfer]==0.19.0" --extra-index-url https://download.pytorch.org/whl/cu129
pip install -r builder/requirements.txt
```

## 7. Test the Worker

### Option A: Quick Test with test_input.json

Create a test input file and run the handler directly:

```bash
cat > test_input.json << 'EOF'
{
  "id": "test-1",
  "input": {
    "openai_route": "/v1/chat/completions",
    "openai_input": {
      "model": "gemma-4-26b-moe",
      "messages": [{"role": "user", "content": "Hello, what model are you?"}],
      "max_tokens": 100,
      "temperature": 0.3
    }
  }
}
EOF

# Set env vars
export MODEL_NAME=cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit
export QUANTIZATION=awq
export MAX_MODEL_LEN=8192
export GPU_MEMORY_UTILIZATION=0.95
export OPENAI_SERVED_MODEL_NAME_OVERRIDE=gemma-4-26b-moe
export ENABLE_PREFIX_CACHING=true

# Run — the SDK detects test_input.json and runs locally
python3 src/handler.py
```

The handler will load the model (first run downloads from HuggingFace ~7GB), process the test input, print the result, and exit.

### Option B: Local API Server

Start a FastAPI server that mimics RunPod's serverless API:

```bash
python3 src/handler.py --rp_serve_api --rp_api_port 8000
```

Then from another terminal (or your local machine via SSH tunnel):

```bash
# Sync request
curl -X POST http://localhost:8000/runsync \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "openai_route": "/v1/chat/completions",
      "openai_input": {
        "model": "gemma-4-26b-moe",
        "messages": [{"role": "user", "content": "Write a fibonacci function in Python"}],
        "max_tokens": 300
      }
    }
  }'
```

API endpoints available:
- `POST /runsync` — synchronous (blocks until done)
- `POST /run` — async (returns job ID)
- `GET /stream/{job_id}` — stream results
- `GET /status/{job_id}` — check job status
- `GET /docs` — Swagger UI

### Option C: Docker Build + Run on Pod

Test the full container image as it would run on RunPod Serverless:

```bash
cd /workspace/gemmaVllmWorker

docker build -t gemma-worker:test .

docker run --gpus all \
  -e MODEL_NAME=cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit \
  -e QUANTIZATION=awq \
  -e MAX_MODEL_LEN=8192 \
  -e GPU_MEMORY_UTILIZATION=0.95 \
  -e OPENAI_SERVED_MODEL_NAME_OVERRIDE=gemma-4-26b-moe \
  -e ENABLE_PREFIX_CACHING=true \
  -p 8000:8000 \
  gemma-worker:test --rp_serve_api --rp_api_port 8000
```

## 8. SSH Tunnel (hit the pod API from your Mac)

If you're running the API server on the pod (Option B or C), you can tunnel it to your local machine:

```bash
# From your Mac (not the pod)
ssh -L 8000:localhost:8000 root@<ip> -p <port> -i ~/.runpod/ssh/RunPod-Key-Go
```

Now `http://localhost:8000` on your Mac hits the pod's API server. You can use the Swagger UI at `http://localhost:8000/docs`.

## 9. File Transfer

`runpodctl` has built-in peer-to-peer file transfer (uses croc under the hood). No API key needed, works between any two machines:

```bash
# On your Mac — send a file
runpodctl send ./some-file.py
# Output: code is: 8338-galileo-collect-fidel

# On the pod — receive it
runpodctl receive 8338-galileo-collect-fidel
```

Note: `runpodctl` is pre-installed on every RunPod pod.

## 10. Clean Up

```bash
# Stop the pod (keeps volume, can restart later)
runpodctl pod stop <pod-id>

# Or delete it entirely
runpodctl pod delete <pod-id>
```

Stopped pods don't incur GPU charges but do incur small volume storage charges. Delete when you're done to avoid any charges.

## Troubleshooting

**Model download is slow**: Set `export HF_HUB_ENABLE_HF_TRANSFER=1` and `pip install hf-transfer` for faster downloads.

**Out of VRAM**: Lower `MAX_MODEL_LEN` (try 4096) or set `ENFORCE_EAGER=true` to disable CUDA graphs (saves ~1-2GB).

**Pod won't start**: Check GPU availability with `runpodctl gpu list`. Try a different GPU type or datacenter.

**SSH connection refused**: Wait 1-2 minutes after pod creation for it to boot. Check `runpodctl pod list` — status should be `RUNNING`.
