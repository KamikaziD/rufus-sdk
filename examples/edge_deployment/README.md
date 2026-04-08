# Ruvon Edge Deployment Demo

This directory contains everything you need to demo the Ruvon Cloud Policy Engine
with a heterogeneous device fleet.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              Docker (localhost:8000)                             │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │  ruvon-server    │────│   PostgreSQL     │                   │
│  │  Policy Engine   │    │   (persistence)  │                   │
│  └────────┬─────────┘    └──────────────────┘                   │
└───────────┼─────────────────────────────────────────────────────┘
            │
    ┌───────┴───────┬───────────────┐
    │               │               │
┌───▼───┐     ┌─────▼─────┐   ┌─────▼─────┐
│MacBook│     │Raspberry  │   │  NVIDIA   │
│M4 Max │     │Pi 5       │   │  Jetson   │
└───────┘     └───────────┘   └───────────┘
 APPLE_SILICON  CPU (ARM64)    NVIDIA GPU
 Neural Engine  8GB RAM        TensorRT
```

## Quick Start

### Step 1: Start the Cloud Platform

```bash
cd docker
docker compose up -d
```

Verify it's running:
```bash
curl http://localhost:8000/health
# Should return: {"status":"healthy"...}
```

### Step 2: Create Sample Policies

```bash
python examples/edge_deployment/setup_policies.py
```

This creates three sample policies:
- `Vision_Model_Q1_2024` - Routes vision models by hardware capability
- `Fraud_Detection_Rules` - Routes fraud detection by GPU/RAM
- `Edge_Runtime_Update` - Routes runtime updates by platform

### Step 3: Run Your MacBook as an Edge Device

```bash
python examples/edge_deployment/run_edge_macbook.py
```

You should see output like:
```
  Hardware:        Darwin arm64
  Apple Silicon:   Yes
  Neural Engine:   Yes

  Policy Check-in:
  Artifact:        vision_v2_coreml.pex
  Message:         Update available
```

### Step 4: (Optional) Run a Raspberry Pi

On your Raspberry Pi 5:
```bash
# Install dependencies
pip install httpx

# Copy the script (or clone the repo)
# Then run:
python run_edge_rpi.py --cloud-url http://YOUR_MAC_IP:8000
```

You should see:
```
  Hardware:        Linux aarch64
  Model:           Raspberry Pi 5 Model B Rev 1.0

  Policy Check-in:
  Artifact:        vision_lite_v2_onnx_arm.pex
  Message:         Update available
```

## Files

| File | Description |
|------|-------------|
| `run_edge_macbook.py` | Edge agent for MacBook with Apple Silicon |
| `run_edge_rpi.py` | Edge agent for Raspberry Pi 5 |
| `setup_policies.py` | Creates sample deployment policies |
| `README.md` | This file |

## API Endpoints

Access the cloud API docs at: http://localhost:8000/docs

Key endpoints:
- `POST /api/v1/update-check` - Device check-in (Policy Engine)
- `GET /api/v1/policies` - List all policies
- `POST /api/v1/policies` - Create a policy
- `GET /api/v1/rollout/status` - View deployment status

## Policy Matching

The Policy Engine evaluates rules in priority order:

| Hardware | Artifact Assigned |
|----------|------------------|
| MacBook M4 (Apple Silicon) | `vision_v2_coreml.pex` |
| NVIDIA Jetson (4GB+ VRAM) | `vision_heavy_v2_tensorrt.pex` |
| Raspberry Pi 5 (ARM64) | `vision_lite_v2_onnx_arm.pex` |
| Coral Edge TPU | `vision_v2_edgetpu.pex` |
| Generic x86 server | `vision_lite_v2_onnx_cpu.pex` |

## Troubleshooting

### Cannot connect to cloud
```bash
# Check if Docker is running
docker compose ps

# Check logs
docker compose logs ruvon-server
```

### Policy not matching
```bash
# Check the hardware identity being sent
# Look for "Hardware Identity" section in output

# Verify policy conditions match your hardware
# See the policy rules in setup_policies.py
```

### Raspberry Pi cannot reach Mac
```bash
# On Mac, find your IP:
ifconfig | grep "inet "

# On Pi, test connectivity:
curl http://YOUR_MAC_IP:8000/health
```
