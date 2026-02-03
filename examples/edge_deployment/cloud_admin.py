#!/usr/bin/env python3
"""
Cloud Admin Tool - Manage Devices and View Rollout Status

Usage:
    python cloud_admin.py list-devices [status]
    python cloud_admin.py device-info <device-id>
    python cloud_admin.py list-policies [status]
    python cloud_admin.py rollout-status [policy-id]
    python cloud_admin.py send-command <device-id> <command-type> [data-json] [retry-policy-json]
    python cloud_admin.py list-commands <device-id> [status]
    python cloud_admin.py command-status <device-id> <command-id>

Command Examples:
    python cloud_admin.py send-command macbook-m4-001 restart '{"delay_seconds": 10}'
    python cloud_admin.py send-command macbook-m4-001 health_check
    python cloud_admin.py send-command macbook-m4-001 backup '{"target": "cloud"}'
    python cloud_admin.py send-command macbook-m4-001 emergency_stop '{"reason": "Security incident"}'

Command Examples with Retry:
    # Exponential backoff (3 retries)
    python cloud_admin.py send-command macbook-m4-001 sync_now '{}' '{"max_retries": 3, "initial_delay_seconds": 10, "backoff_strategy": "exponential"}'

    # Fixed delay (5 retries, 30s each)
    python cloud_admin.py send-command rpi5-001 backup '{"target": "cloud"}' '{"max_retries": 5, "initial_delay_seconds": 30, "backoff_strategy": "fixed"}'
"""

import asyncio
import httpx
import json
import sys
from typing import Optional

CLOUD_URL = "http://localhost:8000"


async def list_devices(status: Optional[str] = None):
    """List all registered devices."""
    print("\n" + "="*70)
    print("  REGISTERED DEVICES")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/devices",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                devices = data.get("devices", [])

                if not devices:
                    print("  No devices registered\n")
                    return

                print(f"  Total devices: {data['total']}\n")

                for device in devices:
                    print(f"  Device: {device.get('device_id')}")
                    print(f"    Type:         {device.get('device_type', 'N/A')}")
                    print(f"    Name:         {device.get('device_name', 'N/A')}")
                    print(f"    Status:       {device.get('status', 'N/A')}")
                    print(f"    Merchant:     {device.get('merchant_id', 'N/A')}")
                    print(f"    Registered:   {device.get('registered_at', 'N/A')}")
                    print(f"    Last Seen:    {device.get('last_heartbeat_at', 'Never')}")
                    print()
            else:
                print(f"  Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}")
            print(f"    Make sure the cloud is running\n")


async def get_device_info(device_id: str):
    """Get detailed info about a specific device."""
    print("\n" + "="*70)
    print(f"  DEVICE INFO: {device_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/api/v1/devices/{device_id}")

            if response.status_code == 200:
                device = response.json()
                for key, value in device.items():
                    print(f"  {key:20s}: {value}")
                print()
            elif response.status_code == 404:
                print(f"  Device not found: {device_id}\n")
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_policies(status: Optional[str] = None):
    """List all deployment policies."""
    print("\n" + "="*70)
    print("  DEPLOYMENT POLICIES")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/policies",
                params=params
            )

            if response.status_code == 200:
                policies = response.json()

                if not policies:
                    print("  No policies defined\n")
                    return

                for policy in policies:
                    status_icon = "●" if policy['status'] == 'active' else "○"
                    print(f"  {status_icon} {policy['policy_name']} v{policy['version']}")
                    print(f"    Status:      {policy['status']}")
                    print(f"    Rules:       {len(policy.get('rules', []))}")
                    print(f"    Rollout:     {policy.get('rollout', {}).get('strategy', 'N/A')}")
                    print(f"    Created:     {policy.get('created_at', 'N/A')}")
                    print()
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def rollout_status(policy_id: Optional[str] = None):
    """Get rollout status across all devices."""
    print("\n" + "="*70)
    print("  ROLLOUT STATUS")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if policy_id:
                params["policy_id"] = policy_id

            response = await client.get(
                f"{CLOUD_URL}/api/v1/rollout/status",
                params=params
            )

            if response.status_code == 200:
                data = response.json()

                print(f"  Total Devices:    {data['total_devices']}")
                print(f"\n  Status Breakdown:")
                for status, count in data.get('status_breakdown', {}).items():
                    print(f"    {status:20s}: {count}")

                print(f"\n  By Policy:")
                for pid, statuses in data.get('by_policy', {}).items():
                    print(f"    Policy {pid[:8]}...")
                    for status, count in statuses.items():
                        print(f"      {status:18s}: {count}")
                print()
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def send_command(
    device_id: str,
    command_type: str,
    data: Optional[dict] = None,
    retry_policy: Optional[dict] = None
):
    """Send a command to a specific device."""
    print("\n" + "="*70)
    print(f"  SEND COMMAND: {command_type} → {device_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            payload = {
                "type": command_type,
                "data": data or {}
            }

            # Add retry policy if provided
            if retry_policy:
                payload["retry_policy"] = retry_policy
                print(f"  Retry Policy:     {retry_policy.get('max_retries', 0)} retries, "
                      f"{retry_policy.get('backoff_strategy', 'exponential')} backoff")

            response = await client.post(
                f"{CLOUD_URL}/api/v1/devices/{device_id}/commands",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Command sent successfully")
                print(f"  Command ID:       {result.get('command_id')}")
                print(f"  Status:           {result.get('status')}")
                print(f"  Delivery Method:  {result.get('delivery_method')}")
                if result.get('delivered_at'):
                    print(f"  Delivered:        {result.get('delivered_at')}")
                else:
                    print(f"  Queued:           {result.get('created_at')}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_commands(device_id: str, status: Optional[str] = None):
    """List commands for a specific device."""
    print("\n" + "="*70)
    print(f"  DEVICE COMMANDS: {device_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/devices/{device_id}/commands",
                params=params
            )

            if response.status_code == 200:
                commands = response.json()

                if not commands:
                    print("  No commands found\n")
                    return

                for cmd in commands:
                    status_icon = {
                        'pending': '⏳',
                        'delivered': '📤',
                        'completed': '✓',
                        'failed': '✗'
                    }.get(cmd['status'], '○')

                    print(f"  {status_icon} {cmd['command_type']} (ID: {cmd['command_id'][:8]}...)")
                    print(f"    Status:       {cmd['status']}")
                    print(f"    Created:      {cmd.get('created_at', 'N/A')}")
                    if cmd.get('completed_at'):
                        print(f"    Completed:    {cmd['completed_at']}")
                    if cmd.get('error'):
                        print(f"    Error:        {cmd['error']}")
                    print()
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_command_status(device_id: str, command_id: str):
    """Get status of a specific command."""
    print("\n" + "="*70)
    print(f"  COMMAND STATUS: {command_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/devices/{device_id}/commands/{command_id}/status"
            )

            if response.status_code == 200:
                cmd = response.json()

                print(f"  Command Type:     {cmd['command_type']}")
                print(f"  Status:           {cmd['status']}")
                print(f"  Device ID:        {cmd['device_id']}")
                print(f"  Created:          {cmd.get('created_at', 'N/A')}")

                if cmd.get('delivered_at'):
                    print(f"  Delivered:        {cmd['delivered_at']}")
                if cmd.get('completed_at'):
                    print(f"  Completed:        {cmd['completed_at']}")

                if cmd.get('result'):
                    print(f"\n  Result:")
                    print(f"    {json.dumps(cmd['result'], indent=4)}")

                if cmd.get('error'):
                    print(f"\n  Error:            {cmd['error']}")
                print()
            elif response.status_code == 404:
                print(f"  Command not found: {command_id}\n")
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python cloud_admin.py list-devices [status]")
        print("  python cloud_admin.py device-info <device-id>")
        print("  python cloud_admin.py list-policies [status]")
        print("  python cloud_admin.py rollout-status [policy-id]")
        print("  python cloud_admin.py send-command <device-id> <command-type> [data-json]")
        print("  python cloud_admin.py list-commands <device-id> [status]")
        print("  python cloud_admin.py command-status <device-id> <command-id>")
        print()
        return

    command = sys.argv[1]

    if command == "list-devices":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        await list_devices(status)

    elif command == "device-info":
        if len(sys.argv) < 3:
            print("Error: device-id required")
            return
        await get_device_info(sys.argv[2])

    elif command == "list-policies":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        await list_policies(status)

    elif command == "rollout-status":
        policy_id = sys.argv[2] if len(sys.argv) > 2 else None
        await rollout_status(policy_id)

    elif command == "send-command":
        if len(sys.argv) < 4:
            print("Error: device-id and command-type required")
            return
        device_id = sys.argv[2]
        command_type = sys.argv[3]
        data = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        retry_policy = json.loads(sys.argv[5]) if len(sys.argv) > 5 else None
        await send_command(device_id, command_type, data, retry_policy)

    elif command == "list-commands":
        if len(sys.argv) < 3:
            print("Error: device-id required")
            return
        device_id = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) > 3 else None
        await list_commands(device_id, status)

    elif command == "command-status":
        if len(sys.argv) < 4:
            print("Error: device-id and command-id required")
            return
        await get_command_status(sys.argv[2], sys.argv[3])

    else:
        print(f"Unknown command: {command}")


if __name__ == '__main__':
    asyncio.run(main())
