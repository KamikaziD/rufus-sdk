#!/usr/bin/env python3
"""
Rufus Edge Runner for Raspberry Pi 5

This script runs a Rufus Edge agent on a Raspberry Pi 5,
demonstrating:
- ARM64 hardware detection
- CPU-only inference (no GPU)
- Policy Engine routing to lightweight artifacts
- Network connectivity to cloud

Usage:
    # On your Mac, start the cloud platform:
    cd docker && docker compose up -d

    # Copy this script to the Raspberry Pi
    scp -r examples/edge_deployment/ pi@raspberrypi:~/rufus/

    # On the Raspberry Pi:
    cd ~/rufus/edge_deployment
    python run_edge_rpi.py --cloud-url http://YOUR_MAC_IP:8000

Requirements:
    - Raspberry Pi 5 (8GB recommended)
    - Raspberry Pi OS (64-bit)
    - Python 3.10+
    - Network access to the cloud server
"""

import argparse
import asyncio
import logging
import os
import platform
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('rufus.edge.rpi')


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Rufus Edge Agent for Raspberry Pi 5'
    )
    parser.add_argument(
        '--cloud-url',
        default=os.getenv('RUFUS_CLOUD_URL', 'http://localhost:8000'),
        help='URL of the Rufus Cloud Control Plane'
    )
    parser.add_argument(
        '--device-id',
        default=os.getenv('RUFUS_DEVICE_ID', f'rpi5-{platform.node()[:8]}'),
        help='Unique device identifier'
    )
    parser.add_argument(
        '--api-key',
        default=os.getenv('RUFUS_API_KEY', 'demo-api-key-rpi'),
        help='API key for cloud authentication'
    )
    parser.add_argument(
        '--poll-interval',
        type=int,
        default=60,
        help='Polling interval in seconds (default: 60)'
    )
    parser.add_argument(
        '--continuous',
        action='store_true',
        help='Run in continuous mode (poll forever)'
    )
    return parser.parse_args()


def get_system_info():
    """Get Raspberry Pi system information."""
    info = {
        'model': 'Unknown',
        'ram_total_mb': 0,
        'ram_free_mb': 0,
        'cpu_temp': 0,
        'cpu_freq': 0,
    }

    # Try to get Raspberry Pi model
    try:
        with open('/proc/device-tree/model', 'r') as f:
            info['model'] = f.read().strip('\x00').strip()
    except:
        pass

    # Get memory info
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    info['ram_total_mb'] = int(line.split()[1]) // 1024
                elif line.startswith('MemAvailable:'):
                    info['ram_free_mb'] = int(line.split()[1]) // 1024
    except:
        pass

    # Get CPU temperature
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            info['cpu_temp'] = int(f.read().strip()) / 1000
    except:
        pass

    # Get CPU frequency
    try:
        with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq', 'r') as f:
            info['cpu_freq'] = int(f.read().strip()) // 1000  # MHz
    except:
        pass

    return info


def get_hardware_identity(device_id: str, system_info: dict):
    """Build hardware identity for cloud check-in."""
    return {
        'device_id': device_id,
        'hw': 'CPU',  # Raspberry Pi has no GPU acceleration
        'platform': platform.system(),
        'arch': platform.machine(),
        'accelerators': ['cpu'],
        'ram_total': system_info.get('ram_total_mb'),
        'ram_free': system_info.get('ram_free_mb'),
        'supports_fp16': False,
        'supports_int8': True,
        'supports_neural_engine': False,
        'metadata': {
            'model': system_info.get('model'),
            'cpu_temp': system_info.get('cpu_temp'),
            'cpu_freq': system_info.get('cpu_freq'),
        }
    }


async def check_for_updates(client, cloud_url: str, identity: dict, api_key: str):
    """Check cloud for artifact updates."""
    try:
        response = await client.post(
            f"{cloud_url}/api/v1/update-check",
            json=identity,
            headers={"X-API-Key": api_key}
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Update check failed: HTTP {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Update check error: {e}")
        return None


async def main():
    """Main entry point."""
    args = parse_args()

    print("\n" + "#"*60)
    print("#" + " "*58 + "#")
    print("#    RUFUS EDGE - Raspberry Pi 5" + " "*24 + "#")
    print("#" + " "*58 + "#")
    print("#"*60)

    # Get system info
    print("\n" + "="*60)
    print("  SYSTEM INFORMATION")
    print("="*60 + "\n")

    system_info = get_system_info()
    print(f"  Model:           {system_info['model']}")
    print(f"  Platform:        {platform.system()} {platform.machine()}")
    print(f"  RAM Total:       {system_info['ram_total_mb']} MB")
    print(f"  RAM Available:   {system_info['ram_free_mb']} MB")
    print(f"  CPU Temp:        {system_info['cpu_temp']:.1f}°C")
    print(f"  CPU Freq:        {system_info['cpu_freq']} MHz")

    # Build hardware identity
    print("\n" + "="*60)
    print("  HARDWARE IDENTITY")
    print("="*60 + "\n")

    identity = get_hardware_identity(args.device_id, system_info)
    print(f"  Device ID:       {identity['device_id']}")
    print(f"  Hardware Type:   {identity['hw']}")
    print(f"  Architecture:    {identity['arch']}")
    print(f"  Accelerators:    {identity['accelerators']}")

    # Check cloud connectivity
    print("\n" + "="*60)
    print("  CLOUD CONNECTIVITY")
    print("="*60 + "\n")

    try:
        import httpx
    except ImportError:
        print("  ERROR: httpx not installed")
        print("  Install with: pip install httpx")
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{args.cloud_url}/health")
            if response.status_code == 200:
                print(f"  ✓ Connected to {args.cloud_url}")
            else:
                print(f"  ✗ Cloud unhealthy: HTTP {response.status_code}")
                return
        except Exception as e:
            print(f"  ✗ Cannot connect to {args.cloud_url}")
            print(f"    Error: {e}")
            print(f"\n  Make sure the cloud is running and accessible")
            return

        # Check for updates
        print("\n" + "="*60)
        print("  POLICY ENGINE CHECK-IN")
        print("="*60 + "\n")

        update_info = await check_for_updates(
            client, args.cloud_url, identity, args.api_key
        )

        if update_info:
            print(f"  Needs Update:    {update_info.get('needs_update')}")
            print(f"  Artifact:        {update_info.get('artifact', 'N/A')}")
            print(f"  Policy Version:  {update_info.get('policy_version', 'N/A')}")
            print(f"  Message:         {update_info.get('message', 'N/A')}")

            if update_info.get('needs_update'):
                print(f"\n  Would download: {update_info.get('artifact_url')}")

        # Continuous mode
        if args.continuous:
            print("\n" + "="*60)
            print("  CONTINUOUS POLLING MODE")
            print("="*60 + "\n")

            print(f"  Polling every {args.poll_interval} seconds...")
            print("  Press Ctrl+C to stop\n")

            poll_count = 0
            while True:
                poll_count += 1
                timestamp = datetime.now().strftime('%H:%M:%S')

                # Update system info (RAM, temp may change)
                system_info = get_system_info()
                identity = get_hardware_identity(args.device_id, system_info)

                update_info = await check_for_updates(
                    client, args.cloud_url, identity, args.api_key
                )

                if update_info:
                    status = "UPDATE" if update_info.get('needs_update') else "OK"
                    artifact = update_info.get('artifact', '-')
                    temp = system_info.get('cpu_temp', 0)
                    ram = system_info.get('ram_free_mb', 0)
                    print(f"  [{timestamp}] #{poll_count}: {status} | {artifact} | {temp:.1f}°C | {ram}MB free")
                else:
                    print(f"  [{timestamp}] #{poll_count}: Cloud unreachable")

                await asyncio.sleep(args.poll_interval)

        else:
            print("\n" + "="*60)
            print("  NEXT STEPS")
            print("="*60 + "\n")

            print("  Run in continuous mode:")
            print(f"    python {sys.argv[0]} --continuous --cloud-url {args.cloud_url}")
            print()
            print("  Or set up as a systemd service for production.")
            print()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  Shutting down...")
