#!/usr/bin/env python3
"""
Setup Sample Policies for Heterogeneous Fleet Demo

This script creates sample deployment policies that demonstrate
the Cloud Policy Engine's ability to route different artifacts
to different hardware types.

Usage:
    # Start the cloud platform first:
    cd docker && docker compose up -d

    # Then run this script:
    python examples/edge_deployment/setup_policies.py
"""

import asyncio
import httpx
import json
import os
import sys
from datetime import datetime
from uuid import uuid4

# Configuration
CLOUD_URL = os.getenv('RUVON_CLOUD_URL', 'http://localhost:8000')

# ─────────────────────────────────────────────────────────────────────────────
# Sample Policies
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_POLICIES = [
    {
        "policy_name": "Vision_Model_Q1_2024",
        "description": "Deploy optimized vision models to edge devices based on hardware capabilities",
        "version": "2.0.0",
        "status": "active",
        "rules": [
            {
                "condition": "hardware == 'NVIDIA' and vram_free >= 4096",
                "artifact": "vision_heavy_v2_tensorrt.pex",
                "artifact_hash": "sha256:abc123heavy",
                "description": "High-accuracy TensorRT model for NVIDIA GPUs with 4GB+ VRAM",
                "priority": 100
            },
            {
                "condition": "hardware == 'NVIDIA'",
                "artifact": "vision_lite_v2_tensorrt.pex",
                "artifact_hash": "sha256:abc123lite",
                "description": "Lightweight TensorRT model for NVIDIA GPUs with limited VRAM",
                "priority": 90
            },
            {
                "condition": "hardware == 'APPLE_SILICON' and supports_neural_engine",
                "artifact": "vision_v2_coreml.pex",
                "artifact_hash": "sha256:def456coreml",
                "description": "CoreML model optimized for Apple Neural Engine (M1/M2/M3/M4)",
                "priority": 100
            },
            {
                "condition": "hardware == 'APPLE_SILICON'",
                "artifact": "vision_v2_mlx.pex",
                "artifact_hash": "sha256:def456mlx",
                "description": "MLX model for Apple Silicon GPU (fallback if no ANE)",
                "priority": 90
            },
            {
                "condition": "hardware == 'EDGE_TPU'",
                "artifact": "vision_v2_edgetpu.pex",
                "artifact_hash": "sha256:ghi789edgetpu",
                "description": "Quantized INT8 model for Coral Edge TPU",
                "priority": 100
            },
            {
                "condition": "arch == 'aarch64' or arch == 'arm64'",
                "artifact": "vision_lite_v2_onnx_arm.pex",
                "artifact_hash": "sha256:jkl012arm",
                "description": "Lightweight ONNX model for ARM devices (Raspberry Pi, etc.)",
                "priority": 50
            },
            {
                "condition": "default",
                "artifact": "vision_lite_v2_onnx_cpu.pex",
                "artifact_hash": "sha256:mno345cpu",
                "description": "Generic ONNX model for x86/x64 CPUs",
                "priority": 0
            }
        ],
        "rollout": {
            "strategy": "canary",
            "percentage": 100,  # 100% for demo, use 10% for production
            "failure_threshold": "5%",
            "batch_size": 10,
            "batch_delay_seconds": 300
        },
        "tags": {
            "team": "ml-ops",
            "environment": "demo",
            "quarter": "Q1-2024"
        }
    },
    {
        "policy_name": "Fraud_Detection_Rules",
        "description": "Deploy fraud detection models with different accuracy levels",
        "version": "1.5.0",
        "status": "active",
        "rules": [
            {
                "condition": "hardware == 'NVIDIA' or hardware == 'APPLE_SILICON'",
                "artifact": "fraud_detection_full_v1.5.pex",
                "artifact_hash": "sha256:fraud001full",
                "description": "Full fraud detection with deep learning (GPU required)",
                "priority": 100
            },
            {
                "condition": "ram_free >= 2048",
                "artifact": "fraud_detection_medium_v1.5.pex",
                "artifact_hash": "sha256:fraud001med",
                "description": "Medium-weight fraud detection for devices with 2GB+ RAM",
                "priority": 50
            },
            {
                "condition": "default",
                "artifact": "fraud_detection_lite_v1.5.pex",
                "artifact_hash": "sha256:fraud001lite",
                "description": "Lightweight rule-based fraud detection for low-resource devices",
                "priority": 0
            }
        ],
        "rollout": {
            "strategy": "staged",
            "percentage": 100,
            "failure_threshold": "2%",
            "batch_size": 5,
            "batch_delay_seconds": 600,
            "stages": ["test", "canary", "production"]
        },
        "tags": {
            "team": "security",
            "compliance": "PCI-DSS"
        }
    },
    {
        "policy_name": "Edge_Runtime_Update",
        "description": "Deploy Rufus runtime updates based on platform",
        "version": "0.2.0",
        "status": "active",
        "rules": [
            {
                "condition": "platform == 'Darwin' and arch == 'arm64'",
                "artifact": "rufus_runtime_v0.2.0_macos_arm64.pex",
                "artifact_hash": "sha256:runtime_macos_arm",
                "description": "macOS ARM64 runtime (Apple Silicon)",
                "priority": 100
            },
            {
                "condition": "platform == 'Darwin'",
                "artifact": "rufus_runtime_v0.2.0_macos_x64.pex",
                "artifact_hash": "sha256:runtime_macos_x64",
                "description": "macOS x64 runtime (Intel Macs)",
                "priority": 90
            },
            {
                "condition": "platform == 'Linux' and arch == 'aarch64'",
                "artifact": "rufus_runtime_v0.2.0_linux_arm64.pex",
                "artifact_hash": "sha256:runtime_linux_arm",
                "description": "Linux ARM64 runtime (Raspberry Pi, Jetson)",
                "priority": 100
            },
            {
                "condition": "platform == 'Linux'",
                "artifact": "rufus_runtime_v0.2.0_linux_x64.pex",
                "artifact_hash": "sha256:runtime_linux_x64",
                "description": "Linux x64 runtime (generic servers)",
                "priority": 90
            },
            {
                "condition": "default",
                "artifact": "rufus_runtime_v0.2.0_generic.pex",
                "artifact_hash": "sha256:runtime_generic",
                "description": "Generic Python runtime (fallback)",
                "priority": 0
            }
        ],
        "rollout": {
            "strategy": "immediate",
            "percentage": 100,
            "failure_threshold": "1%"
        },
        "tags": {
            "type": "runtime",
            "critical": "true"
        }
    }
]


async def create_policy(client: httpx.AsyncClient, policy: dict) -> bool:
    """Create a single policy."""
    try:
        response = await client.post(
            f"{CLOUD_URL}/api/v1/policies",
            json=policy
        )

        if response.status_code == 200:
            data = response.json()
            print(f"  ✓ Created: {policy['policy_name']} (ID: {data.get('id', 'N/A')[:8]}...)")
            return True
        else:
            print(f"  ✗ Failed: {policy['policy_name']} - HTTP {response.status_code}")
            print(f"    Response: {response.text[:200]}")
            return False

    except Exception as e:
        print(f"  ✗ Error: {policy['policy_name']} - {e}")
        return False


async def list_policies(client: httpx.AsyncClient):
    """List all policies."""
    try:
        response = await client.get(f"{CLOUD_URL}/api/v1/policies")

        if response.status_code == 200:
            policies = response.json()
            print(f"\n  Total policies: {len(policies)}\n")

            for p in policies:
                status = p.get('status', 'unknown')
                status_icon = "●" if status == 'active' else "○"
                print(f"    {status_icon} {p['policy_name']} v{p['version']} [{status}]")
                print(f"      Rules: {len(p.get('rules', []))}")
                print(f"      Rollout: {p.get('rollout', {}).get('strategy', 'N/A')}")
                print()
        else:
            print(f"  Failed to list policies: HTTP {response.status_code}")

    except Exception as e:
        print(f"  Error listing policies: {e}")


async def test_hardware_matching(client: httpx.AsyncClient):
    """Test hardware matching for different device types."""
    print("\n" + "="*60)
    print("  TESTING HARDWARE MATCHING")
    print("="*60)

    test_devices = [
        {
            "device_id": "macbook-m4-001",
            "hw": "APPLE_SILICON",
            "platform": "Darwin",
            "arch": "arm64",
            "supports_neural_engine": True,
            "ram_free": 65536,
            "description": "MacBook Pro M4 Max"
        },
        {
            "device_id": "jetson-001",
            "hw": "NVIDIA",
            "platform": "Linux",
            "arch": "aarch64",
            "vram_free": 8192,
            "ram_free": 16384,
            "description": "NVIDIA Jetson AGX"
        },
        {
            "device_id": "rpi5-001",
            "hw": "CPU",
            "platform": "Linux",
            "arch": "aarch64",
            "ram_free": 4096,
            "description": "Raspberry Pi 5 8GB"
        },
        {
            "device_id": "coral-001",
            "hw": "EDGE_TPU",
            "platform": "Linux",
            "arch": "aarch64",
            "ram_free": 2048,
            "description": "Coral Dev Board"
        },
        {
            "device_id": "server-001",
            "hw": "CPU",
            "platform": "Linux",
            "arch": "x86_64",
            "ram_free": 32768,
            "description": "Generic Linux Server"
        }
    ]

    print()
    for device in test_devices:
        desc = device.pop('description')
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/update-check",
                json=device,
                headers={"X-API-Key": "test-key"}
            )

            if response.status_code == 200:
                data = response.json()
                artifact = data.get('artifact', 'N/A')
                print(f"  {desc}:")
                print(f"    → {artifact}")
            else:
                print(f"  {desc}: HTTP {response.status_code}")

        except Exception as e:
            print(f"  {desc}: Error - {e}")

        print()


async def main():
    """Main entry point."""
    print("\n" + "#"*60)
    print("#    RUFUS CLOUD - Policy Setup" + " "*25 + "#")
    print("#"*60)

    # Check cloud connectivity
    print("\n" + "="*60)
    print("  CONNECTING TO CLOUD")
    print("="*60 + "\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/health")
            if response.status_code == 200:
                print(f"  ✓ Connected to {CLOUD_URL}")
            else:
                print(f"  ✗ Cloud unhealthy: HTTP {response.status_code}")
                return
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}")
            print(f"\n  Start the cloud platform first:")
            print(f"    cd docker && docker compose up -d")
            return

        # Create policies
        print("\n" + "="*60)
        print("  CREATING POLICIES")
        print("="*60 + "\n")

        created = 0
        for policy in SAMPLE_POLICIES:
            if await create_policy(client, policy):
                created += 1

        print(f"\n  Created {created}/{len(SAMPLE_POLICIES)} policies")

        # List policies
        print("\n" + "="*60)
        print("  REGISTERED POLICIES")
        print("="*60)

        await list_policies(client)

        # Test hardware matching
        await test_hardware_matching(client)

    print("\n" + "="*60)
    print("  NEXT STEPS")
    print("="*60 + "\n")

    print("  1. Run the MacBook edge agent:")
    print("     python examples/edge_deployment/run_edge_macbook.py")
    print()
    print("  2. Run the Raspberry Pi edge agent (on the Pi):")
    print("     python examples/edge_deployment/run_edge_rpi.py")
    print()
    print("  3. View the API docs:")
    print(f"     {CLOUD_URL}/docs")
    print()


if __name__ == '__main__':
    asyncio.run(main())
