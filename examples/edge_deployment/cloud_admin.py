#!/usr/bin/env python3
"""
Cloud Admin Tool - Manage Devices and View Rollout Status

Usage:
    python cloud_admin.py list-devices
    python cloud_admin.py list-policies
    python cloud_admin.py rollout-status
    python cloud_admin.py device-info <device-id>
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


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python cloud_admin.py list-devices [status]")
        print("  python cloud_admin.py device-info <device-id>")
        print("  python cloud_admin.py list-policies [status]")
        print("  python cloud_admin.py rollout-status [policy-id]")
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

    else:
        print(f"Unknown command: {command}")


if __name__ == '__main__':
    asyncio.run(main())
