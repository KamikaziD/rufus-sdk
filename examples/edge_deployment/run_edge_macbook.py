#!/usr/bin/env python3
"""
Rufus Edge Runner for MacBook (Apple Silicon)

This script runs a Rufus Edge agent on your MacBook Pro M4 Max,
demonstrating:
- Apple Silicon detection (Neural Engine, GPU)
- Policy Engine integration with cloud
- Hardware-optimized inference provider selection

Usage:
    # First, start the cloud platform:
    cd docker && docker compose up -d

    # Then run this script:
    python examples/edge_deployment/run_edge_macbook.py

Requirements:
    - MacBook with Apple Silicon (M1/M2/M3/M4)
    - Docker running the cloud platform on localhost:8000
    - Python 3.10+ with rufus-sdk installed
"""

import asyncio
import logging
import os
import sys
from datetime import datetime

# Add project root to path
project_root = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(project_root, 'src'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('rufus.edge.macbook')

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CLOUD_URL = os.getenv('RUFUS_CLOUD_URL', 'http://localhost:8000')
DEVICE_ID = os.getenv('RUFUS_DEVICE_ID', 'macbook-m4-001')
API_KEY = os.getenv('RUFUS_API_KEY', 'demo-api-key-macbook')
ARTIFACTS_DIR = os.path.join(project_root, 'artifacts')
MODELS_DIR = os.path.join(project_root, 'models')

print(f"Configuration: {API_KEY}, {CLOUD_URL}, Device ID: {DEVICE_ID}")


async def detect_hardware():
    """Detect and display hardware capabilities."""
    print("\n" + "="*60)
    print("  HARDWARE DETECTION")
    print("="*60 + "\n")

    from rufus.utils.platform import (
        get_platform_info,
        is_apple_silicon,
        has_apple_neural_engine,
        get_recommended_onnx_providers,
        get_recommended_runtime,
    )

    info = get_platform_info()

    print(f"  Platform:        {info.system} {info.machine}")
    print(f"  Apple Silicon:   {'Yes' if info.is_apple_silicon else 'No'}")
    print(f"  Neural Engine:   {'Yes' if has_apple_neural_engine() else 'No'}")
    print(f"  Accelerators:    {[a.value for a in info.accelerators]}")
    print(f"  Recommended:     {get_recommended_runtime()}")
    print(f"  ONNX Providers:  {get_recommended_onnx_providers()}")

    return info


async def create_hardware_identity():
    """Create hardware identity for cloud check-in."""
    from rufus.implementations.inference.factory import InferenceFactory

    factory = InferenceFactory()
    identity = factory.get_hardware_identity(DEVICE_ID)

    print("\n" + "="*60)
    print("  HARDWARE IDENTITY (sent to Cloud)")
    print("="*60 + "\n")

    id_dict = identity.to_dict()
    for key, value in id_dict.items():
        if value is not None and value != [] and value != {}:
            print(f"  {key:20s}: {value}")

    return identity


async def check_for_updates(identity):
    """Check cloud for artifact updates based on hardware."""
    import httpx

    print("\n" + "="*60)
    print("  POLICY ENGINE CHECK-IN")
    print("="*60 + "\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/update-check",
                json=identity.to_dict(),
                headers={"X-API-Key": API_KEY}
            )

            if response.status_code == 200:
                data = response.json()
                print(f"  Needs Update:    {data.get('needs_update')}")
                print(f"  Artifact:        {data.get('artifact', 'N/A')}")
                print(
                    f"  Policy Version:  {data.get('policy_version', 'N/A')}")
                print(f"  Message:         {data.get('message', 'N/A')}")
                return data
            else:
                print(f"  Check-in failed: HTTP {response.status_code}")
                print(f"  Response: {response.text}")
                return None

        except httpx.ConnectError:
            print(f"  ERROR: Cannot connect to cloud at {CLOUD_URL}")
            print(
                f"         Make sure Docker is running: cd docker && docker compose up -d")
            return None


async def create_inference_provider():
    """Create hardware-optimized inference provider."""
    from rufus.implementations.inference.factory import (
        InferenceFactory,
        ProviderPreference,
    )

    print("\n" + "="*60)
    print("  INFERENCE PROVIDER")
    print("="*60 + "\n")

    factory = InferenceFactory()

    # Auto-detect best provider
    provider = await factory.create_provider(preference=ProviderPreference.AUTO)

    print(f"  Runtime:         {provider.runtime.value}")
    print(f"  Provider Type:   {type(provider).__name__}")

    # For ONNX, show execution providers
    if hasattr(provider, 'providers'):
        print(f"  ONNX Providers:  {provider.providers}")

    return provider


async def demo_inference(provider):
    """Run a simple inference demo."""
    import numpy as np

    print("\n" + "="*60)
    print("  INFERENCE DEMO")
    print("="*60 + "\n")

    # Check if we have a test model
    test_model_path = os.path.join(MODELS_DIR, 'test_model.onnx')

    if not os.path.exists(test_model_path):
        print(f"  No test model found at {test_model_path}")
        print(f"  Skipping inference demo.")
        print(f"  (Place an ONNX model there to test inference)")
        return

    try:
        # Load model
        metadata = await provider.load_model(
            model_path=test_model_path,
            model_name="test_model",
            model_version="1.0.0"
        )
        print(f"  Model loaded: {metadata.name} v{metadata.version}")
        print(f"  Input shapes: {metadata.input_shapes}")

        # Create dummy input
        # This would need to match your actual model's input
        dummy_input = np.random.randn(1, 10).astype(np.float32)

        # Run inference
        result = await provider.run_inference("test_model", {"input": dummy_input})

        if result.success:
            print(f"  Inference time: {result.inference_time_ms:.2f}ms")
            print(f"  Output keys: {list(result.outputs.keys())}")
        else:
            print(f"  Inference failed: {result.error_message}")

    except Exception as e:
        print(f"  Inference error: {e}")


async def run_edge_loop():
    """Main edge agent loop with automatic updates."""
    print("\n" + "="*60)
    print("  EDGE AGENT LOOP (with Auto-Update)")
    print("="*60 + "\n")

    print("  Starting continuous polling...")
    print("  Updates will be automatically installed with Saga rollback")
    print("  Press Ctrl+C to stop\n")

    from rufus.implementations.inference.factory import InferenceFactory
    from artifact_updater import ArtifactUpdater, UpdateInstruction
    from command_handler import CommandHandler

    factory = InferenceFactory()
    updater = ArtifactUpdater(
        artifacts_dir=ARTIFACTS_DIR,
        cloud_url=CLOUD_URL,
        api_key=API_KEY
    )

    # Initialize command handler
    command_handler = CommandHandler(
        device_id=DEVICE_ID,
        cloud_url=CLOUD_URL,
        api_key=API_KEY
    )

    poll_count = 0
    poll_interval = 60  # seconds
    heartbeat_interval = 30  # Send heartbeat every 30 seconds
    last_heartbeat = 0
    current_artifact = None  # Track currently installed artifact

    import httpx
    import time

    # WebSocket handler for critical commands
    async def websocket_handler():
        """Maintain WebSocket connection for critical commands."""
        import websockets
        while True:
            try:
                ws_url = CLOUD_URL.replace(
                    "http://", "ws://").replace("https://", "wss://")
                ws_url = f"{ws_url}/api/v1/devices/{DEVICE_ID}/ws"

                async with websockets.connect(ws_url) as websocket:
                    logger.info("WebSocket connected for critical commands")

                    while True:
                        message = await websocket.recv()
                        import json
                        data = json.loads(message)

                        if data.get('type') == 'command':
                            command = data.get('command')
                            logger.info(
                                f"Received critical command via WebSocket: {command.get('command_type')}")
                            await command_handler.process_commands([command])
                        elif data.get('type') == 'ping':
                            await websocket.send(json.dumps({"type": "pong"}))
            except Exception as e:
                logger.warning(
                    f"WebSocket connection lost: {e}, reconnecting in 10s...")
                await asyncio.sleep(10)

    # Start WebSocket handler in background (runs independently)
    asyncio.create_task(websocket_handler())

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            poll_count += 1
            timestamp = datetime.now().strftime('%H:%M:%S')
            current_time = time.time()

            # Send heartbeat if interval has passed
            if current_time - last_heartbeat >= heartbeat_interval:
                try:
                    response = await client.post(
                        f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/heartbeat",
                        json={
                            "device_status": "online",
                            "active_workflows": 0,
                            "pending_sync": 0,
                            "metrics": {}
                        },
                        headers={"X-API-Key": API_KEY}
                    )
                    last_heartbeat = current_time

                    # Process commands from heartbeat response
                    if response.status_code == 200:
                        heartbeat_data = response.json()
                        commands = heartbeat_data.get('commands', [])
                        if commands:
                            logger.info(
                                f"Received {len(commands)} command(s) from heartbeat")
                            await command_handler.process_commands(commands)
                except Exception as e:
                    logger.warning(f"Heartbeat failed: {e}")

            try:
                identity = factory.get_hardware_identity(DEVICE_ID)
                identity_dict = identity.to_dict()
                identity_dict['current_artifact'] = current_artifact

                response = await client.post(
                    f"{CLOUD_URL}/api/v1/update-check",
                    json=identity_dict,
                    headers={"X-API-Key": API_KEY}
                )

                if response.status_code == 200:
                    data = response.json()
                    needs_update = data.get('needs_update')
                    artifact = data.get('artifact', '-')

                    status_str = "UPDATE AVAILABLE" if needs_update else "UP-TO-DATE"
                    print(
                        f"  [{timestamp}] Poll #{poll_count}: {status_str} | {artifact}")

                    if needs_update:
                        print(f"\n  {'─'*58}")
                        print(f"  UPDATE DETECTED: {artifact}")
                        print(f"  {'─'*58}")

                        # Create update instruction
                        instruction = UpdateInstruction(
                            needs_update=True,
                            artifact=data.get('artifact'),
                            artifact_url=data.get('artifact_url'),
                            artifact_hash=data.get('artifact_hash'),
                            policy_id=data.get('policy_id'),
                            policy_version=data.get('policy_version'),
                            message=data.get('message')
                        )

                        # Progress callback
                        def update_progress(status, message):
                            print(f"    [{status.value}] {message}")

                        # Perform update with Saga rollback
                        result = await updater.perform_update(
                            instruction,
                            DEVICE_ID,
                            current_artifact,
                            update_progress
                        )

                        if result.success:
                            print(f"  ✓ Update completed: {artifact}")
                            current_artifact = artifact
                        else:
                            print(f"  ✗ Update failed: {result.error}")
                            if result.rollback_performed:
                                print(f"  ↶ Rollback successful - system restored")
                            else:
                                print(
                                    f"  ⚠ Rollback failed - manual intervention may be needed")

                        print(f"  {'─'*58}\n")
                else:
                    print(
                        f"  [{timestamp}] Poll #{poll_count}: HTTP {response.status_code}")

            except httpx.ConnectError:
                print(f"  [{timestamp}] Poll #{poll_count}: Cloud unreachable")
            except Exception as e:
                print(f"  [{timestamp}] Poll #{poll_count}: Error - {e}")

            await asyncio.sleep(poll_interval)


async def main():
    """Main entry point."""
    print("\n" + "#"*60)
    print("#" + " "*58 + "#")
    print("#    RUFUS EDGE - MacBook Pro M4 Max" + " "*20 + "#")
    print("#" + " "*58 + "#")
    print("#"*60)

    # Step 1: Detect hardware
    info = await detect_hardware()

    if not info.is_apple_silicon:
        print("\n  WARNING: This device is not Apple Silicon!")
        print("           Some features may not be available.\n")

    # Step 2: Create hardware identity
    identity = await create_hardware_identity()

    # Step 3: Check for updates from cloud
    update_info = await check_for_updates(identity)

    # Step 4: Create inference provider
    try:
        provider = await create_inference_provider()

        # Step 5: Demo inference
        await demo_inference(provider)

        # Cleanup
        await provider.close()
    except Exception as e:
        print(f"\n  Could not create inference provider: {e}")
        print("  (This is OK if ONNX Runtime is not installed)")

    # Step 6: Ask about continuous mode
    print("\n" + "="*60)
    print("  NEXT STEPS")
    print("="*60 + "\n")

    print("  Options:")
    print("    1. Run continuous edge loop (polls cloud every 60s)")
    print("    2. Exit")
    print()

    try:
        choice = input("  Enter choice [1/2]: ").strip()
        if choice == '1':
            await run_edge_loop()
    except KeyboardInterrupt:
        print("\n\n  Shutting down...")

    print("\n  Edge agent stopped.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Interrupted by user.")
