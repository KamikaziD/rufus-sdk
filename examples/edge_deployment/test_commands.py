#!/usr/bin/env python3
"""
Command System Test Script

Demonstrates the hybrid command delivery system:
1. Send commands to devices
2. Check command status
3. Verify delivery and execution

Usage:
    # Start the cloud server first:
    cd docker && docker compose up -d

    # Start an edge device:
    python run_edge_macbook.py

    # Run this test script:
    python test_commands.py
"""

import asyncio
import httpx
import json
import time
from datetime import datetime


CLOUD_URL = "http://localhost:8000"
DEVICE_ID = "macbook-m4-001"  # Change this to your device ID


async def send_command(client: httpx.AsyncClient, command_type: str, data: dict = None):
    """Send a command to the device."""
    print(f"\n{'='*70}")
    print(f"  SENDING COMMAND: {command_type}")
    print(f"{'='*70}")

    payload = {
        "type": command_type,
        "data": data or {}
    }

    response = await client.post(
        f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/commands",
        json=payload
    )

    if response.status_code == 200:
        result = response.json()
        print(f"  ✓ Command sent successfully")
        print(f"  Command ID:       {result['command_id']}")
        print(f"  Status:           {result['status']}")
        print(f"  Delivery Method:  {result['delivery_method']}")
        return result['command_id']
    else:
        print(f"  ✗ Failed: HTTP {response.status_code}")
        print(f"  {response.text}")
        return None


async def check_command_status(client: httpx.AsyncClient, command_id: str):
    """Check the status of a command."""
    response = await client.get(
        f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/commands/{command_id}/status"
    )

    if response.status_code == 200:
        return response.json()
    return None


async def wait_for_completion(client: httpx.AsyncClient, command_id: str, timeout: int = 60):
    """Wait for command to complete."""
    print(f"\n  Waiting for command to complete (timeout: {timeout}s)...")

    start_time = time.time()
    while time.time() - start_time < timeout:
        status_data = await check_command_status(client, command_id)

        if status_data:
            status = status_data['status']
            print(f"  Status: {status}", end="\r")

            if status == "completed":
                print(f"\n  ✓ Command completed successfully")
                if status_data.get('result'):
                    print(f"  Result: {json.dumps(status_data['result'], indent=2)}")
                return True
            elif status == "failed":
                print(f"\n  ✗ Command failed")
                if status_data.get('error'):
                    print(f"  Error: {status_data['error']}")
                return False

        await asyncio.sleep(2)

    print(f"\n  ⚠ Timeout waiting for command completion")
    return False


async def test_routine_command(client: httpx.AsyncClient):
    """Test routine command (delivered via heartbeat)."""
    print("\n" + "="*70)
    print("  TEST 1: ROUTINE COMMAND (Heartbeat Delivery)")
    print("="*70)

    # Send a health_check command (NORMAL priority → heartbeat delivery)
    command_id = await send_command(client, "health_check")

    if command_id:
        # Wait up to 40 seconds (device heartbeat is every 30s)
        await wait_for_completion(client, command_id, timeout=40)


async def test_critical_command(client: httpx.AsyncClient):
    """Test critical command (delivered via WebSocket)."""
    print("\n" + "="*70)
    print("  TEST 2: CRITICAL COMMAND (WebSocket Delivery)")
    print("="*70)

    # Send a disable_transactions command (CRITICAL priority → websocket delivery)
    command_id = await send_command(
        client,
        "disable_transactions",
        {"reason": "Test - will re-enable immediately"}
    )

    if command_id:
        # Wait up to 5 seconds (WebSocket should deliver immediately)
        success = await wait_for_completion(client, command_id, timeout=5)

        if success:
            # Re-enable transactions
            print("\n  Re-enabling transactions...")
            enable_cmd_id = await send_command(client, "enable_transactions")
            if enable_cmd_id:
                await wait_for_completion(client, enable_cmd_id, timeout=5)


async def test_command_with_params(client: httpx.AsyncClient):
    """Test command with parameters."""
    print("\n" + "="*70)
    print("  TEST 3: COMMAND WITH PARAMETERS")
    print("="*70)

    # Send a backup command with parameters
    command_id = await send_command(
        client,
        "backup",
        {"target": "local"}
    )

    if command_id:
        await wait_for_completion(client, command_id, timeout=40)


async def list_recent_commands(client: httpx.AsyncClient):
    """List recent commands for the device."""
    print("\n" + "="*70)
    print("  RECENT COMMANDS")
    print("="*70)

    response = await client.get(
        f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}/commands"
    )

    if response.status_code == 200:
        commands = response.json()

        if not commands:
            print("  No commands found\n")
            return

        for cmd in commands[:5]:  # Show last 5 commands
            status_icon = {
                'pending': '⏳',
                'delivered': '📤',
                'completed': '✓',
                'failed': '✗'
            }.get(cmd['status'], '○')

            print(f"\n  {status_icon} {cmd['command_type']}")
            print(f"    Status:   {cmd['status']}")
            print(f"    Created:  {cmd.get('created_at', 'N/A')}")

            if cmd.get('completed_at'):
                created = datetime.fromisoformat(cmd['created_at'].replace('Z', '+00:00'))
                completed = datetime.fromisoformat(cmd['completed_at'].replace('Z', '+00:00'))
                duration = (completed - created).total_seconds()
                print(f"    Duration: {duration:.1f}s")
    else:
        print(f"  Error: HTTP {response.status_code}\n")


async def main():
    """Main test flow."""
    print("\n" + "#"*70)
    print("#" + " "*68 + "#")
    print("#    RUFUS COMMAND SYSTEM TEST" + " "*39 + "#")
    print("#" + " "*68 + "#")
    print("#"*70)

    print(f"\nCloud URL: {CLOUD_URL}")
    print(f"Device ID: {DEVICE_ID}")

    # Check connectivity
    print("\nChecking cloud connectivity...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/health")
            if response.status_code == 200:
                print("✓ Cloud is online\n")
            else:
                print(f"✗ Cloud unhealthy: HTTP {response.status_code}\n")
                return
        except Exception as e:
            print(f"✗ Cannot connect to cloud: {e}\n")
            print("Make sure the cloud server is running:")
            print("  cd docker && docker compose up -d\n")
            return

        # Check device status
        print(f"Checking device status...")
        try:
            response = await client.get(f"{CLOUD_URL}/api/v1/devices/{DEVICE_ID}")
            if response.status_code == 200:
                device = response.json()
                status = device.get('status', 'unknown')
                print(f"✓ Device found (status: {status})\n")

                if status == 'offline':
                    print("⚠ WARNING: Device is offline!")
                    print("  Commands will be queued until device comes online.")
                    print("  Start the edge device:")
                    print("    python run_edge_macbook.py\n")
            else:
                print(f"✗ Device not found: {DEVICE_ID}")
                print("  Register the device first:")
                print("    python run_edge_macbook.py\n")
                return
        except Exception as e:
            print(f"✗ Error checking device: {e}\n")
            return

        # Run tests
        try:
            await test_routine_command(client)
            await asyncio.sleep(2)

            await test_critical_command(client)
            await asyncio.sleep(2)

            await test_command_with_params(client)
            await asyncio.sleep(2)

            await list_recent_commands(client)

            print("\n" + "="*70)
            print("  TESTS COMPLETE")
            print("="*70)
            print()

        except KeyboardInterrupt:
            print("\n\nTests interrupted by user\n")


if __name__ == '__main__':
    asyncio.run(main())
