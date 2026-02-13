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
    python cloud_admin.py broadcast-command <filter-json> <command-type> [data-json] [rollout-json]
    python cloud_admin.py list-broadcasts [status]
    python cloud_admin.py broadcast-status <broadcast-id>
    python cloud_admin.py cancel-broadcast <broadcast-id>
    python cloud_admin.py list-templates
    python cloud_admin.py get-template <template-name>
    python cloud_admin.py apply-template <template-name> <device-id> [variables-json]
    python cloud_admin.py apply-template-broadcast <template-name> <filter-json> [variables-json] [rollout-json]

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

Broadcast Examples:
    # All devices in merchant
    python cloud_admin.py broadcast-command '{"merchant_id": "merchant-123", "status": "online"}' update_config '{"floor_limit": 50.00}'

    # Progressive rollout (canary: 10%, 50%, 100%)
    python cloud_admin.py broadcast-command '{"device_type": "macbook"}' restart '{"delay_seconds": 10}' '{"strategy": "canary", "phases": [0.1, 0.5, 1.0], "wait_seconds": 300}'

    # Check broadcast status
    python cloud_admin.py broadcast-status <broadcast-id>

    # Cancel broadcast
    python cloud_admin.py cancel-broadcast <broadcast-id>

Template Examples:
    # List available templates
    python cloud_admin.py list-templates

    # Get template details
    python cloud_admin.py get-template soft-restart

    # Apply template to single device
    python cloud_admin.py apply-template soft-restart macbook-m4-001 '{"delay_seconds": 60}'

    # Apply template as broadcast
    python cloud_admin.py apply-template-broadcast security-lockdown '{"merchant_id": "merchant-123"}'

Command Versioning:
    python cloud_admin.py list-command-versions [command-type] [--active-only]
    python cloud_admin.py get-command-version <command-type> <version>
    python cloud_admin.py validate-command <command-type> <version> <data-json>
    python cloud_admin.py command-changelog <command-type> [from-version] [to-version]

Webhook Management:
    python cloud_admin.py list-webhooks [--active-only]
    python cloud_admin.py get-webhook <webhook-id>
    python cloud_admin.py create-webhook <webhook-json>
    python cloud_admin.py update-webhook <webhook-id> <updates-json>
    python cloud_admin.py delete-webhook <webhook-id>
    python cloud_admin.py webhook-deliveries <webhook-id> [status] [limit]
    python cloud_admin.py test-webhook <url> <event-type> <event-data-json> [secret]

Webhook Examples:
    # Create webhook
    python cloud_admin.py create-webhook '{"webhook_id": "my-webhook", "name": "Device Events", "url": "https://example.com/webhook", "events": ["device.online", "device.offline"], "secret": "my-secret"}'

    # List webhooks
    python cloud_admin.py list-webhooks --active-only

    # Get delivery history
    python cloud_admin.py webhook-deliveries my-webhook failed 50
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


async def broadcast_command(
    filter_json: dict,
    command_type: str,
    data: Optional[dict] = None,
    rollout_config: Optional[dict] = None
):
    """Broadcast command to multiple devices."""
    print("\n" + "="*70)
    print(f"  BROADCAST COMMAND: {command_type}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "command_type": command_type,
                "command_data": data or {},
                "target_filter": filter_json
            }

            if rollout_config:
                payload["rollout_config"] = rollout_config

            print(f"  Target Filter:    {json.dumps(filter_json)}")
            if rollout_config:
                print(f"  Rollout Strategy: {rollout_config.get('strategy', 'all_at_once')}")

            response = await client.post(
                f"{CLOUD_URL}/api/v1/broadcasts",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n  ✓ Broadcast created successfully")
                print(f"  Broadcast ID:     {result.get('broadcast_id')}")
                print(f"  Status:           {result.get('status')}")
                print(f"  Message:          {result.get('message')}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_broadcast_status(broadcast_id: str):
    """Get broadcast execution progress."""
    print("\n" + "="*70)
    print(f"  BROADCAST STATUS: {broadcast_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/api/v1/broadcasts/{broadcast_id}")

            if response.status_code == 200:
                progress = response.json()

                print(f"  Command Type:     {progress['command_type']}")
                print(f"  Status:           {progress['status']}")
                print(f"\n  Progress:")
                print(f"    Total Devices:    {progress['total_devices']}")
                print(f"    Completed:        {progress['completed_devices']}")
                print(f"    Failed:           {progress['failed_devices']}")
                print(f"    In Progress:      {progress['in_progress_devices']}")
                print(f"    Pending:          {progress['pending_devices']}")
                print(f"\n  Rates:")
                print(f"    Success Rate:     {progress['success_rate']:.1%}")
                print(f"    Failure Rate:     {progress['failure_rate']:.1%}")
                print(f"\n  Timeline:")
                print(f"    Created:          {progress.get('created_at', 'N/A')}")
                if progress.get('started_at'):
                    print(f"    Started:          {progress['started_at']}")
                if progress.get('completed_at'):
                    print(f"    Completed:        {progress['completed_at']}")
                if progress.get('error_message'):
                    print(f"\n  Error:            {progress['error_message']}")
                print()

            elif response.status_code == 404:
                print(f"  Broadcast not found: {broadcast_id}\n")
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_broadcasts(status: Optional[str] = None):
    """List recent broadcasts."""
    print("\n" + "="*70)
    print("  RECENT BROADCASTS")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/broadcasts",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                broadcasts = data.get("broadcasts", [])

                if not broadcasts:
                    print("  No broadcasts found\n")
                    return

                for bc in broadcasts:
                    status_icon = {
                        'pending': '⏳',
                        'in_progress': '🔄',
                        'completed': '✓',
                        'failed': '✗',
                        'paused': '⏸',
                        'cancelled': '🚫'
                    }.get(bc['status'], '○')

                    print(f"  {status_icon} {bc['command_type']} (ID: {bc['broadcast_id'][:8]}...)")
                    print(f"    Status:       {bc['status']}")
                    print(f"    Devices:      {bc['completed_devices']}/{bc['total_devices']} completed")
                    print(f"    Created:      {bc.get('created_at', 'N/A')}")
                    print()

            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def cancel_broadcast(broadcast_id: str):
    """Cancel ongoing broadcast."""
    print("\n" + "="*70)
    print(f"  CANCEL BROADCAST: {broadcast_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.delete(f"{CLOUD_URL}/api/v1/broadcasts/{broadcast_id}")

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Broadcast cancelled successfully")
                print(f"  Broadcast ID:     {result['broadcast_id']}")
                print(f"  Status:           {result['status']}")
                print()
            elif response.status_code == 400:
                print(f"  ✗ Cannot cancel broadcast (already completed or not found)")
                print(f"  {response.text}\n")
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_templates():
    """List available command templates."""
    print("\n" + "="*70)
    print("  COMMAND TEMPLATES")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/api/v1/templates")

            if response.status_code == 200:
                data = response.json()
                templates = data.get("templates", [])

                if not templates:
                    print("  No templates found\n")
                    return

                for tmpl in templates:
                    tags_str = ", ".join(tmpl.get("tags", []))
                    print(f"  📋 {tmpl['template_name']} (v{tmpl.get('version', '1.0.0')})")
                    print(f"    Description:  {tmpl['description']}")
                    print(f"    Commands:     {tmpl['command_count']}")
                    print(f"    Tags:         {tags_str}")
                    print()

            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_template(template_name: str):
    """Get template details."""
    print("\n" + "="*70)
    print(f"  TEMPLATE: {template_name}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(f"{CLOUD_URL}/api/v1/templates/{template_name}")

            if response.status_code == 200:
                tmpl = response.json()

                print(f"  Name:         {tmpl['template_name']}")
                print(f"  Description:  {tmpl['description']}")
                print(f"  Version:      {tmpl.get('version', '1.0.0')}")
                print(f"  Tags:         {', '.join(tmpl.get('tags', []))}")

                print(f"\n  Commands:")
                for idx, cmd in enumerate(tmpl['commands'], start=1):
                    print(f"    {idx}. {cmd['type']}")
                    if cmd.get('data'):
                        print(f"       Data: {json.dumps(cmd['data'])}")

                if tmpl.get('variables'):
                    print(f"\n  Variables:")
                    for var in tmpl['variables']:
                        required_str = " (required)" if var.get('required') else ""
                        default_str = f" [default: {var.get('default')}]" if var.get('default') is not None else ""
                        print(f"    • {var['name']}: {var.get('description', '')}{required_str}{default_str}")

                print()

            elif response.status_code == 404:
                print(f"  Template not found: {template_name}\n")
            else:
                print(f"  Error: HTTP {response.status_code}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def apply_template_to_device(
    template_name: str,
    device_id: str,
    variables: Optional[dict] = None
):
    """Apply template to a single device."""
    print("\n" + "="*70)
    print(f"  APPLY TEMPLATE: {template_name} → {device_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            payload = {
                "device_id": device_id,
                "variables": variables or {}
            }

            response = await client.post(
                f"{CLOUD_URL}/api/v1/templates/{template_name}/apply",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Template applied successfully")
                print(f"  Template:       {result['template_name']}")
                print(f"  Device:         {result['device_id']}")
                print(f"  Commands:       {len(result['command_ids'])} created")
                print(f"  Command IDs:    {', '.join([cid[:8] + '...' for cid in result['command_ids']])}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def apply_template_broadcast(
    template_name: str,
    target_filter: dict,
    variables: Optional[dict] = None,
    rollout_config: Optional[dict] = None
):
    """Apply template as broadcast to multiple devices."""
    print("\n" + "="*70)
    print(f"  APPLY TEMPLATE (BROADCAST): {template_name}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "target_filter": target_filter,
                "variables": variables or {}
            }

            if rollout_config:
                payload["rollout_config"] = rollout_config

            print(f"  Template:       {template_name}")
            print(f"  Target Filter:  {json.dumps(target_filter)}")

            response = await client.post(
                f"{CLOUD_URL}/api/v1/templates/{template_name}/apply",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"\n  ✓ Template applied as broadcast")
                print(f"  Template:       {result['template_name']}")
                print(f"  Broadcast ID:   {result['broadcast_id']}")
                print(f"  Message:        {result['message']}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═════════════════════════════════════════════════════════════════════════
# Command Batch Functions
# ═════════════════════════════════════════════════════════════════════════

async def create_batch(device_id: str, commands_json: str, execution_mode: str = "sequential"):
    """
    Create an atomic multi-command batch.

    Args:
        device_id: Target device ID
        commands_json: JSON array of commands with type, data, and optional sequence
        execution_mode: "sequential" or "parallel"

    Examples:
        Sequential: '[{"type":"clear_cache","data":{},"sequence":1},{"type":"sync_now","data":{},"sequence":2}]'
        Parallel: '[{"type":"health_check","data":{}},{"type":"sync_now","data":{}}]'
    """
    async with httpx.AsyncClient() as client:
        try:
            commands = json.loads(commands_json)

            payload = {
                "device_id": device_id,
                "commands": commands,
                "execution_mode": execution_mode
            }

            response = await client.post(
                f"{CLOUD_URL}/api/v1/batches",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Batch created successfully")
            print(f"  Batch ID: {result['batch_id']}")
            print(f"  Device: {device_id}")
            print(f"  Total Commands: {result['total_commands']}")
            print(f"  Execution Mode: {result['execution_mode']}")
            print(f"  Status: {result['status']}\n")

        except json.JSONDecodeError as e:
            print(f"  ✗ Invalid JSON: {e}\n")
        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_batch_status(batch_id: str):
    """Get batch execution progress."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/batches/{batch_id}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            progress = response.json()

            print(f"\nBatch: {progress['batch_id']}")
            print(f"  Device: {progress['device_id']}")
            print(f"  Status: {progress['status']}")
            print(f"  Execution Mode: {progress['execution_mode']}")
            print(f"  Total Commands: {progress['total_commands']}")
            print(f"  Completed: {progress['completed_commands']}")
            print(f"  Failed: {progress['failed_commands']}")
            print(f"  Pending: {progress['pending_commands']}")
            print(f"  Success Rate: {progress['success_rate']:.1%}")
            print(f"  Created: {progress['created_at']}")

            if progress['started_at']:
                print(f"  Started: {progress['started_at']}")
            if progress['completed_at']:
                print(f"  Completed: {progress['completed_at']}")
            if progress['error_message']:
                print(f"  Error: {progress['error_message']}")

            # Show command statuses
            if progress['command_statuses']:
                print(f"\n  Commands:")
                for cmd in progress['command_statuses']:
                    status_icon = "✓" if cmd['status'] == "completed" else "✗" if cmd['status'] == "failed" else "⋯"
                    print(f"    {status_icon} [{cmd['sequence']}] {cmd['command_type']} - {cmd['status']}")
                    if cmd.get('error'):
                        print(f"        Error: {cmd['error']}")

            print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_batches(device_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    """List command batches with optional filters."""
    async with httpx.AsyncClient() as client:
        try:
            params = {"limit": limit}
            if device_id:
                params["device_id"] = device_id
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/batches",
                params=params,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            batches = result["batches"]
            count = result["count"]

            if count == 0:
                print("\nNo batches found\n")
                return

            print(f"\nFound {count} batch(es):\n")
            for batch in batches:
                status_icon = "✓" if batch['status'] == "completed" else "✗" if batch['status'] == "failed" else "⋯"
                print(f"{status_icon} {batch['batch_id'][:8]}... ({batch['device_id']})")
                print(f"  Status: {batch['status']} | Mode: {batch['execution_mode']}")
                print(f"  Progress: {batch['completed_commands']}/{batch['total_commands']} completed, {batch['failed_commands']} failed")
                print(f"  Created: {batch['created_at']}")
                print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def cancel_batch(batch_id: str):
    """Cancel a pending batch."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{CLOUD_URL}/api/v1/batches/{batch_id}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Batch cancelled")
            print(f"  Batch ID: {result['batch_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═════════════════════════════════════════════════════════════════════════
# Command Schedule Functions
# ═════════════════════════════════════════════════════════════════════════

async def create_schedule(
    schedule_json: str
):
    """
    Create a command schedule (one-time or recurring).

    Args:
        schedule_json: JSON schedule configuration

    Examples:
        One-time: '{"schedule_name":"Restart","device_id":"dev-001","command_type":"restart","command_data":{},"schedule_type":"one_time","execute_at":"2026-02-05T02:00:00Z"}'
        Recurring: '{"schedule_name":"Daily check","device_id":"dev-001","command_type":"health_check","command_data":{},"schedule_type":"recurring","cron_expression":"0 2 * * *"}'
    """
    async with httpx.AsyncClient() as client:
        try:
            schedule_data = json.loads(schedule_json)

            response = await client.post(
                f"{CLOUD_URL}/api/v1/schedules",
                json=schedule_data,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Schedule created successfully")
            print(f"  Schedule ID: {result['schedule_id']}")
            print(f"  Status: {result['status']}\n")

        except json.JSONDecodeError as e:
            print(f"  ✗ Invalid JSON: {e}\n")
        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_schedule_status(schedule_id: str):
    """Get schedule details and execution history."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/schedules/{schedule_id}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            schedule = response.json()

            print(f"\nSchedule: {schedule['schedule_id']}")
            if schedule['schedule_name']:
                print(f"  Name: {schedule['schedule_name']}")
            print(f"  Device: {schedule['device_id'] or 'Fleet'}")
            print(f"  Command: {schedule['command_type']}")
            print(f"  Type: {schedule['schedule_type']}")
            print(f"  Status: {schedule['status']}")
            print(f"  Execution Count: {schedule['execution_count']}")

            if schedule['max_executions']:
                print(f"  Max Executions: {schedule['max_executions']}")

            if schedule['next_execution_at']:
                print(f"  Next Execution: {schedule['next_execution_at']}")

            if schedule['last_execution_at']:
                print(f"  Last Execution: {schedule['last_execution_at']}")

            if schedule['cron_expression']:
                print(f"  Cron: {schedule['cron_expression']}")
                print(f"  Timezone: {schedule['timezone']}")

            print(f"  Created: {schedule['created_at']}")

            # Show recent executions
            if schedule['recent_executions']:
                print(f"\n  Recent Executions:")
                for exec in schedule['recent_executions']:
                    status_icon = "✓" if exec['status'] == "completed" else "✗" if exec['status'] == "failed" else "⋯"
                    print(f"    {status_icon} #{exec['execution_number']} - {exec['status']}")
                    print(f"       Scheduled: {exec['scheduled_for']}")
                    if exec['executed_at']:
                        print(f"       Executed: {exec['executed_at']}")
                    if exec['error_message']:
                        print(f"       Error: {exec['error_message']}")

            print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_schedules(
    device_id: Optional[str] = None,
    status: Optional[str] = None,
    schedule_type: Optional[str] = None,
    limit: int = 50
):
    """List command schedules with optional filters."""
    async with httpx.AsyncClient() as client:
        try:
            params = {"limit": limit}
            if device_id:
                params["device_id"] = device_id
            if status:
                params["status"] = status
            if schedule_type:
                params["schedule_type"] = schedule_type

            response = await client.get(
                f"{CLOUD_URL}/api/v1/schedules",
                params=params,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            schedules = result["schedules"]
            count = result["count"]

            if count == 0:
                print("\nNo schedules found\n")
                return

            print(f"\nFound {count} schedule(s):\n")
            for schedule in schedules:
                status_icon = "✓" if schedule['status'] == "active" else "⏸" if schedule['status'] == "paused" else "✗"
                print(f"{status_icon} {schedule['schedule_id'][:8]}... - {schedule.get('schedule_name', schedule['command_type'])}")
                print(f"  Device: {schedule['device_id'] or 'Fleet'}")
                print(f"  Type: {schedule['schedule_type']} | Status: {schedule['status']}")
                print(f"  Executions: {schedule['execution_count']}/{schedule['max_executions'] or '∞'}")

                if schedule['next_execution_at']:
                    print(f"  Next: {schedule['next_execution_at']}")

                print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def pause_schedule(schedule_id: str):
    """Pause an active schedule."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/schedules/{schedule_id}/pause",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Schedule paused")
            print(f"  Schedule ID: {result['schedule_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def resume_schedule(schedule_id: str):
    """Resume a paused schedule."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/schedules/{schedule_id}/resume",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Schedule resumed")
            print(f"  Schedule ID: {result['schedule_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def cancel_schedule(schedule_id: str):
    """Cancel a schedule."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{CLOUD_URL}/api/v1/schedules/{schedule_id}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Schedule cancelled")
            print(f"  Schedule ID: {result['schedule_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═════════════════════════════════════════════════════════════════════════
# Audit Log Functions
# ═════════════════════════════════════════════════════════════════════════

async def query_audit_logs(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    device_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100
):
    """Query audit logs."""
    async with httpx.AsyncClient() as client:
        try:
            query = {"limit": limit}

            if start_time:
                query["start_time"] = start_time
            if end_time:
                query["end_time"] = end_time
            if device_id:
                query["device_id"] = device_id
            if event_type:
                query["event_types"] = [event_type]

            response = await client.post(
                f"{CLOUD_URL}/api/v1/audit/query",
                json=query,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            entries = result["entries"]
            total = result["total_count"]

            if total == 0:
                print("\nNo audit logs found\n")
                return

            print(f"\nFound {total} audit log(s) (showing {len(entries)}):\n")

            for entry in entries:
                status_icon = "✓" if entry['status'] == "completed" else "✗" if entry['status'] == "failed" else "⋯"
                print(f"{status_icon} [{entry['timestamp']}] {entry['event_type']}")
                print(f"  Device: {entry['device_id'] or 'N/A'}")
                print(f"  Actor: {entry['actor_type']}/{entry['actor_id']}")

                if entry['command_type']:
                    print(f"  Command: {entry['command_type']}")

                if entry['error_message']:
                    print(f"  Error: {entry['error_message']}")

                if entry['compliance_tags']:
                    print(f"  Tags: {', '.join(entry['compliance_tags'])}")

                print()

            if result['has_more']:
                print(f"  ... and {total - len(entries)} more (use --limit to see more)\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def export_audit_logs(
    output_file: str,
    export_format: str = "json",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    device_id: Optional[str] = None
):
    """Export audit logs to file."""
    async with httpx.AsyncClient() as client:
        try:
            query = {}

            if start_time:
                query["start_time"] = start_time
            if end_time:
                query["end_time"] = end_time
            if device_id:
                query["device_id"] = device_id

            payload = {
                "query": query,
                "format": export_format
            }

            response = await client.post(
                f"{CLOUD_URL}/api/v1/audit/export",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()

            # Write to file
            with open(output_file, 'w') as f:
                f.write(response.text)

            print(f"\n✓ Audit logs exported to {output_file}")
            print(f"  Format: {export_format}")
            print(f"  Size: {len(response.text)} bytes\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")
        except IOError as e:
            print(f"  ✗ Failed to write file: {e}\n")


async def get_audit_stats(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None
):
    """Get audit log statistics."""
    async with httpx.AsyncClient() as client:
        try:
            params = {}
            if start_time:
                params["start_time"] = start_time
            if end_time:
                params["end_time"] = end_time

            response = await client.get(
                f"{CLOUD_URL}/api/v1/audit/stats",
                params=params,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            stats = response.json()

            print(f"\nAudit Log Statistics")
            print(f"  Period: {stats['period']['start']} to {stats['period']['end']}")
            print(f"  Total Events: {stats['total_events']}")
            print(f"  Failed Events: {stats['failed_events']}")

            if stats['events_by_type']:
                print(f"\n  Top Event Types:")
                for event_type, count in list(stats['events_by_type'].items())[:10]:
                    print(f"    {event_type}: {count}")

            if stats['events_by_actor']:
                print(f"\n  Events by Actor Type:")
                for actor_type, count in stats['events_by_actor'].items():
                    print(f"    {actor_type}: {count}")

            print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═════════════════════════════════════════════════════════════════════════
# Authorization Functions
# ═════════════════════════════════════════════════════════════════════════

async def check_authorization(user_id: str, command_type: str, device_type: Optional[str] = None):
    """Check if user is authorized to execute a command."""
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "user_id": user_id,
                "command_type": command_type
            }
            if device_type:
                payload["device_type"] = device_type

            response = await client.post(
                f"{CLOUD_URL}/api/v1/authorization/check",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\nAuthorization Check: {command_type}")
            print(f"  User: {user_id}")
            print(f"  Authorized: {'✓ Yes' if result['authorized'] else '✗ No'}")
            print(f"  Requires Approval: {'Yes' if result['requires_approval'] else 'No'}")
            print(f"  User Roles: {', '.join(result['user_roles'])}")

            if result['missing_roles']:
                print(f"  Missing Roles: {', '.join(result['missing_roles'])}")

            if result['policy']:
                print(f"  Policy: {result['policy']['policy_name']}")
                print(f"  Risk Level: {result['policy']['risk_level']}")
                if result['requires_approval']:
                    print(f"  Approvers Required: {result['policy']['approvers_required']}")

            print(f"  Reason: {result['reason']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def request_approval(approval_json: str):
    """Request approval for a command."""
    async with httpx.AsyncClient() as client:
        try:
            approval_data = json.loads(approval_json)

            response = await client.post(
                f"{CLOUD_URL}/api/v1/approvals",
                json=approval_data,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Approval request created")
            print(f"  Approval ID: {result['approval_id']}")
            print(f"  Status: {result['status']}\n")

        except json.JSONDecodeError as e:
            print(f"  ✗ Invalid JSON: {e}\n")
        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_approval_status(approval_id: str):
    """Get approval request status."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/approvals/{approval_id}",
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            approval = response.json()

            print(f"\nApproval: {approval['approval_id']}")
            print(f"  Command: {approval['command_type']}")
            print(f"  Device: {approval['device_id'] or 'Fleet'}")
            print(f"  Requested By: {approval['requested_by']}")
            print(f"  Requested At: {approval['requested_at']}")
            print(f"  Status: {approval['status']}")
            print(f"  Risk Level: {approval['risk_level']}")
            print(f"  Approvals: {approval['approvers_count']}/{approval['approvers_required']}")
            print(f"  Expires: {approval['expires_at']}")

            if approval['reason']:
                print(f"  Reason: {approval['reason']}")

            if approval['responses']:
                print(f"\n  Responses:")
                for resp in approval['responses']:
                    icon = "✓" if resp['response'] == "approved" else "✗"
                    print(f"    {icon} {resp['approver_id']} - {resp['response']}")
                    if resp['comment']:
                        print(f"       Comment: {resp['comment']}")

            print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_pending_approvals(user_id: Optional[str] = None, status: Optional[str] = None):
    """List approval requests."""
    async with httpx.AsyncClient() as client:
        try:
            params = {}
            if user_id:
                params["user_id"] = user_id
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/approvals",
                params=params,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            approvals = result["approvals"]
            count = result["count"]

            if count == 0:
                print("\nNo approval requests found\n")
                return

            print(f"\nFound {count} approval request(s):\n")
            for approval in approvals:
                status_icon = "⋯" if approval['status'] == "pending" else "✓" if approval['status'] == "approved" else "✗"
                print(f"{status_icon} {approval['approval_id'][:8]}... - {approval['command_type']}")
                print(f"  Device: {approval['device_id'] or 'Fleet'}")
                print(f"  Requested By: {approval['requested_by']}")
                print(f"  Status: {approval['status']} | Risk: {approval['risk_level']}")
                print(f"  Approvals: {approval['approvers_count']}/{approval['approvers_required']}")
                print(f"  Expires: {approval['expires_at']}")
                if approval['reason']:
                    print(f"  Reason: {approval['reason']}")
                print()

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def approve_command(approval_id: str, approver_id: str, comment: Optional[str] = None):
    """Approve a command."""
    async with httpx.AsyncClient() as client:
        try:
            payload = {"approver_id": approver_id}
            if comment:
                payload["comment"] = comment

            response = await client.post(
                f"{CLOUD_URL}/api/v1/approvals/{approval_id}/approve",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Approval recorded")
            print(f"  Approval ID: {result['approval_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def reject_command(approval_id: str, approver_id: str, comment: Optional[str] = None):
    """Reject a command."""
    async with httpx.AsyncClient() as client:
        try:
            payload = {"approver_id": approver_id}
            if comment:
                payload["comment"] = comment

            response = await client.post(
                f"{CLOUD_URL}/api/v1/approvals/{approval_id}/reject",
                json=payload,
                headers={"Authorization": f"Bearer {API_KEY}"}
            )
            response.raise_for_status()
            result = response.json()

            print(f"\n✓ Rejection recorded")
            print(f"  Approval ID: {result['approval_id']}")
            print(f"  Status: {result['status']}\n")

        except httpx.HTTPStatusError as e:
            print(f"  ✗ Error: {e.response.json()}\n")
        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═════════════════════════════════════════════════════════════════════════
# Rate Limiting Functions
# ═════════════════════════════════════════════════════════════════════════

async def get_rate_limit_status(identifier: Optional[str] = None):
    """Get current rate limit status for user or IP."""
    print("\n" + "="*70)
    print("  RATE LIMIT STATUS")
    print("="*70 + "\n")

    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if identifier and identifier.startswith("user:"):
                headers["X-User-ID"] = identifier.replace("user:", "")

            response = await client.get(
                f"{CLOUD_URL}/api/v1/rate-limits/status",
                headers=headers
            )

            if response.status_code == 200:
                result = response.json()
                identifier = result.get("identifier", "Unknown")
                limits = result.get("limits", [])

                print(f"  Identifier: {identifier}")
                print()

                if not limits:
                    print("  No rate limits configured\n")
                    return

                print(f"  {'Rule Name':<30} {'Limit':<10} {'Used':<10} {'Remaining':<10} {'Resets':<20}")
                print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10} {'-'*20}")

                for limit in limits:
                    print(f"  {limit['rule_name']:<30} "
                          f"{limit['limit']:<10} "
                          f"{limit['used']:<10} "
                          f"{limit['remaining']:<10} "
                          f"{limit['resets_at'][:19]:<20}")

                print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def list_rate_limits(is_active: Optional[bool] = None):
    """List all rate limit rules."""
    print("\n" + "="*70)
    print("  RATE LIMIT RULES")
    print("="*70 + "\n")

    async with httpx.AsyncClient() as client:
        try:
            params = {}
            if is_active is not None:
                params["is_active"] = str(is_active).lower()

            response = await client.get(
                f"{CLOUD_URL}/api/v1/admin/rate-limits",
                params=params
            )

            if response.status_code == 200:
                result = response.json()
                rules = result.get("rules", [])

                if not rules:
                    print("  No rate limit rules configured\n")
                    return

                print(f"  Total rules: {result['total']}\n")

                print(f"  {'Rule Name':<25} {'Pattern':<25} {'Scope':<8} {'Limit/Window':<15} {'Active':<8}")
                print(f"  {'-'*25} {'-'*25} {'-'*8} {'-'*15} {'-'*8}")

                for rule in rules:
                    limit_str = f"{rule['limit_per_window']}/{rule['window_seconds']}s"
                    active_str = "✓" if rule['is_active'] else "✗"

                    print(f"  {rule['rule_name']:<25} "
                          f"{rule['resource_pattern']:<25} "
                          f"{rule['scope']:<8} "
                          f"{limit_str:<15} "
                          f"{active_str:<8}")

                print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def update_rate_limit(rule_name: str, limit: int, window: int):
    """Update an existing rate limit rule."""
    print("\n" + "="*70)
    print(f"  UPDATE RATE LIMIT: {rule_name}")
    print("="*70 + "\n")

    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "limit_per_window": limit,
                "window_seconds": window
            }

            print(f"  Rule:   {rule_name}")
            print(f"  Limit:  {limit} requests")
            print(f"  Window: {window} seconds")
            print()

            response = await client.put(
                f"{CLOUD_URL}/api/v1/admin/rate-limits/{rule_name}",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ {result['message']}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def create_rate_limit(
    rule_name: str,
    pattern: str,
    scope: str,
    limit: int,
    window: int
):
    """Create a new rate limit rule."""
    print("\n" + "="*70)
    print("  CREATE RATE LIMIT RULE")
    print("="*70 + "\n")

    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "rule_name": rule_name,
                "resource_pattern": pattern,
                "scope": scope,
                "limit_per_window": limit,
                "window_seconds": window,
                "is_active": True
            }

            print(f"  Rule Name: {rule_name}")
            print(f"  Pattern:   {pattern}")
            print(f"  Scope:     {scope}")
            print(f"  Limit:     {limit} requests / {window} seconds")
            print()

            response = await client.post(
                f"{CLOUD_URL}/api/v1/admin/rate-limits",
                json=payload
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ {result['message']}")
                print()
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Command Versioning Commands
# ═══════════════════════════════════════════════════════════════════════════

async def list_command_versions(command_type: Optional[str] = None, active_only: bool = False):
    """List all command versions."""
    print("\n" + "="*70)
    print("  COMMAND VERSIONS")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if command_type:
                params["command_type"] = command_type
            if active_only:
                params["is_active"] = "true"

            response = await client.get(
                f"{CLOUD_URL}/api/v1/commands/versions",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                versions = data.get("versions", [])

                if not versions:
                    print("  No versions found\n")
                    return

                print(f"  Total versions: {data['total']}\n")

                for version in versions:
                    status = "✓ Active" if version.get("is_active") else "✗ Inactive"
                    deprecated = " [DEPRECATED]" if version.get("is_deprecated") else ""
                    print(f"  {version.get('command_type')} v{version.get('version')} {status}{deprecated}")
                    if version.get("deprecated_reason"):
                        print(f"    Reason: {version.get('deprecated_reason')}")
                    print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_command_version(command_type: str, version: str):
    """Get specific command version details."""
    print("\n" + "="*70)
    print(f"  COMMAND VERSION: {command_type} v{version}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/commands/{command_type}/versions"
            )

            if response.status_code == 200:
                data = response.json()
                versions = data.get("versions", [])

                # Find the specific version
                target_version = None
                for v in versions:
                    if v.get("version") == version:
                        target_version = v
                        break

                if not target_version:
                    print(f"  ✗ Version {version} not found for {command_type}\n")
                    return

                print(f"  Command Type:  {target_version.get('command_type')}")
                print(f"  Version:       {target_version.get('version')}")
                print(f"  Active:        {'Yes' if target_version.get('is_active') else 'No'}")
                print(f"  Deprecated:    {'Yes' if target_version.get('is_deprecated') else 'No'}")
                if target_version.get('deprecated_reason'):
                    print(f"  Reason:        {target_version.get('deprecated_reason')}")
                if target_version.get('changelog'):
                    print(f"  Changelog:     {target_version.get('changelog')}")
                print(f"\n  Schema Definition:")
                print(f"  {json.dumps(target_version.get('schema_definition', {}), indent=2)}\n")

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def validate_command_data(command_type: str, version: str, data_json: str):
    """Validate command data against schema."""
    print("\n" + "="*70)
    print(f"  VALIDATE COMMAND: {command_type} v{version}")
    print("="*70 + "\n")

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}\n")
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/commands/{command_type}/validate",
                json={"version": version, "data": data}
            )

            if response.status_code == 200:
                result = response.json()

                if result.get("valid"):
                    print("  ✓ Command data is valid!\n")
                else:
                    print("  ✗ Command data is invalid\n")
                    print("  Errors:")
                    for error in result.get("errors", []):
                        print(f"    - {error}")
                    print()

                if result.get("warnings"):
                    print("  Warnings:")
                    for warning in result.get("warnings", []):
                        print(f"    - {warning}")
                    print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_command_changelog(command_type: str, from_version: Optional[str] = None, to_version: Optional[str] = None):
    """Get command changelog."""
    print("\n" + "="*70)
    print(f"  CHANGELOG: {command_type}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if from_version:
                params["from_version"] = from_version
            if to_version:
                params["to_version"] = to_version

            response = await client.get(
                f"{CLOUD_URL}/api/v1/commands/{command_type}/changelog",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                changelog = data.get("changelog", [])

                if not changelog:
                    print("  No changelog entries found\n")
                    return

                print(f"  Total entries: {data['total_entries']}\n")

                for entry in changelog:
                    from_v = entry.get("from_version") or "initial"
                    to_v = entry.get("to_version")
                    change_type = entry.get("change_type", "").upper()

                    print(f"  {from_v} → {to_v} [{change_type}]")
                    if entry.get("changes"):
                        changes = entry.get("changes")
                        if isinstance(changes, str):
                            changes = json.loads(changes)
                        print(f"    Changes: {json.dumps(changes, indent=6)}")
                    if entry.get("migration_guide"):
                        print(f"    Migration Guide: {entry.get('migration_guide')}")
                    print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


# ═══════════════════════════════════════════════════════════════════════════
# Webhook Management Commands
# ═══════════════════════════════════════════════════════════════════════════

async def list_webhooks(active_only: bool = False):
    """List all webhook registrations."""
    print("\n" + "="*70)
    print("  WEBHOOKS")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {}
            if active_only:
                params["is_active"] = "true"

            response = await client.get(
                f"{CLOUD_URL}/api/v1/webhooks",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                webhooks = data.get("webhooks", [])

                if not webhooks:
                    print("  No webhooks registered\n")
                    return

                print(f"  Total webhooks: {data['total']}\n")

                for webhook in webhooks:
                    status = "✓ Active" if webhook.get("is_active") else "✗ Inactive"
                    print(f"  {webhook.get('webhook_id')} - {webhook.get('name')} {status}")
                    print(f"    URL:    {webhook.get('url')}")
                    print(f"    Events: {', '.join(webhook.get('events', []))}")
                    print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_webhook(webhook_id: str):
    """Get webhook details."""
    print("\n" + "="*70)
    print(f"  WEBHOOK: {webhook_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(
                f"{CLOUD_URL}/api/v1/webhooks/{webhook_id}"
            )

            if response.status_code == 200:
                webhook = response.json()

                print(f"  Webhook ID:    {webhook.get('webhook_id')}")
                print(f"  Name:          {webhook.get('name')}")
                print(f"  URL:           {webhook.get('url')}")
                print(f"  Events:        {', '.join(webhook.get('events', []))}")
                print(f"  Active:        {'Yes' if webhook.get('is_active') else 'No'}")
                print(f"  Secret:        {'Configured' if webhook.get('secret') else 'None'}")
                if webhook.get('headers'):
                    print(f"  Custom Headers: {json.dumps(webhook.get('headers'), indent=2)}")
                if webhook.get('retry_policy'):
                    print(f"  Retry Policy:  {json.dumps(webhook.get('retry_policy'), indent=2)}")
                print()

            elif response.status_code == 404:
                print(f"  ✗ Webhook not found: {webhook_id}\n")
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def create_webhook(webhook_json: str):
    """Create a new webhook."""
    print("\n" + "="*70)
    print("  CREATE WEBHOOK")
    print("="*70 + "\n")

    try:
        webhook_data = json.loads(webhook_json)
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}\n")
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{CLOUD_URL}/api/v1/webhooks",
                json=webhook_data
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Webhook created successfully!")
                print(f"  Webhook ID: {result.get('webhook_id')}")
                print(f"  Status:     {result.get('status')}")
                print(f"  Events:     {', '.join(result.get('events', []))}\n")

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def update_webhook(webhook_id: str, updates_json: str):
    """Update webhook."""
    print("\n" + "="*70)
    print(f"  UPDATE WEBHOOK: {webhook_id}")
    print("="*70 + "\n")

    try:
        updates = json.loads(updates_json)
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}\n")
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.put(
                f"{CLOUD_URL}/api/v1/webhooks/{webhook_id}",
                json=updates
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Webhook updated successfully!")
                print(f"  Webhook ID: {result.get('webhook_id')}")
                print(f"  Status:     {result.get('status')}\n")

            elif response.status_code == 404:
                print(f"  ✗ Webhook not found: {webhook_id}\n")
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def delete_webhook(webhook_id: str):
    """Delete webhook."""
    print("\n" + "="*70)
    print(f"  DELETE WEBHOOK: {webhook_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.delete(
                f"{CLOUD_URL}/api/v1/webhooks/{webhook_id}"
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Webhook deleted successfully!")
                print(f"  Webhook ID: {result.get('webhook_id')}\n")

            elif response.status_code == 404:
                print(f"  ✗ Webhook not found: {webhook_id}\n")
            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def get_webhook_deliveries(webhook_id: str, status: Optional[str] = None, limit: int = 100):
    """Get webhook delivery history."""
    print("\n" + "="*70)
    print(f"  WEBHOOK DELIVERIES: {webhook_id}")
    print("="*70 + "\n")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            params = {"limit": limit}
            if status:
                params["status"] = status

            response = await client.get(
                f"{CLOUD_URL}/api/v1/webhooks/{webhook_id}/deliveries",
                params=params
            )

            if response.status_code == 200:
                data = response.json()
                deliveries = data.get("deliveries", [])

                if not deliveries:
                    print("  No deliveries found\n")
                    return

                print(f"  Total deliveries: {data['total']}\n")

                for delivery in deliveries:
                    status_icon = "✓" if delivery.get("status") == "delivered" else "✗"
                    print(f"  {status_icon} {delivery.get('event_type')} - {delivery.get('status')}")
                    print(f"    ID:         {delivery.get('id')}")
                    print(f"    Created:    {delivery.get('created_at')}")
                    if delivery.get('http_status'):
                        print(f"    HTTP:       {delivery.get('http_status')}")
                    if delivery.get('error_message'):
                        print(f"    Error:      {delivery.get('error_message')}")
                    print(f"    Attempts:   {delivery.get('attempt_count')}")
                    print()

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def test_webhook(url: str, event_type: str, event_data_json: str, secret: Optional[str] = None):
    """Test webhook delivery."""
    print("\n" + "="*70)
    print(f"  TEST WEBHOOK: {url}")
    print("="*70 + "\n")

    try:
        event_data = json.loads(event_data_json)
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}\n")
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            test_data = {
                "url": url,
                "event_type": event_type,
                "event_data": event_data
            }
            if secret:
                test_data["secret"] = secret

            response = await client.post(
                f"{CLOUD_URL}/api/v1/webhooks/test",
                json=test_data
            )

            if response.status_code == 200:
                result = response.json()
                print(f"  ✓ Webhook test successful!")
                print(f"  Status:     {result.get('status')}")
                print(f"  URL:        {result.get('url')}")
                print(f"  Event Type: {result.get('event_type')}\n")

            else:
                print(f"  ✗ Error: HTTP {response.status_code}")
                print(f"  {response.text}\n")

        except httpx.ConnectError:
            print(f"  ✗ Cannot connect to {CLOUD_URL}\n")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  Device Management:")
        print("    python cloud_admin.py list-devices [status]")
        print("    python cloud_admin.py device-info <device-id>")
        print()
        print("  Policies:")
        print("    python cloud_admin.py list-policies [status]")
        print("    python cloud_admin.py rollout-status [policy-id]")
        print()
        print("  Commands (Single Device):")
        print("    python cloud_admin.py send-command <device-id> <command-type> [data-json] [retry-json]")
        print("    python cloud_admin.py list-commands <device-id> [status]")
        print("    python cloud_admin.py command-status <device-id> <command-id>")
        print()
        print("  Commands (Multi-Device Broadcast):")
        print("    python cloud_admin.py broadcast-command <filter-json> <command-type> [data-json] [rollout-json]")
        print("    python cloud_admin.py list-broadcasts [status]")
        print("    python cloud_admin.py broadcast-status <broadcast-id>")
        print("    python cloud_admin.py cancel-broadcast <broadcast-id>")
        print()
        print("  Command Templates:")
        print("    python cloud_admin.py list-templates")
        print("    python cloud_admin.py get-template <template-name>")
        print("    python cloud_admin.py apply-template <template-name> <device-id> [variables-json]")
        print("    python cloud_admin.py apply-template-broadcast <template-name> <filter-json> [variables-json] [rollout-json]")
        print()
        print("  Command Batches (Atomic Multi-Command):")
        print("    python cloud_admin.py create-batch <device-id> <commands-json> [execution-mode]")
        print("    python cloud_admin.py list-batches [device-id] [status]")
        print("    python cloud_admin.py batch-status <batch-id>")
        print("    python cloud_admin.py cancel-batch <batch-id>")
        print()
        print("  Command Scheduling:")
        print("    python cloud_admin.py create-schedule <schedule-json>")
        print("    python cloud_admin.py list-schedules [device-id] [status] [schedule-type]")
        print("    python cloud_admin.py schedule-status <schedule-id>")
        print("    python cloud_admin.py pause-schedule <schedule-id>")
        print("    python cloud_admin.py resume-schedule <schedule-id>")
        print("    python cloud_admin.py cancel-schedule <schedule-id>")
        print()
        print("  Audit Logs:")
        print("    python cloud_admin.py audit-query [start-time] [end-time] [device-id] [event-type] [limit]")
        print("    python cloud_admin.py audit-export <output-file> [format] [start-time] [end-time] [device-id]")
        print("    python cloud_admin.py audit-stats [start-time] [end-time]")
        print()
        print("  Authorization & Approvals:")
        print("    python cloud_admin.py check-authorization <user-id> <command-type> [device-type]")
        print("    python cloud_admin.py request-approval <approval-json>")
        print("    python cloud_admin.py list-approvals [user-id] [status]")
        print("    python cloud_admin.py approval-status <approval-id>")
        print("    python cloud_admin.py approve-command <approval-id> <approver-id> [comment]")
        print("    python cloud_admin.py reject-command <approval-id> <approver-id> [comment]")
        print()
        print("  Rate Limiting:")
        print("    python cloud_admin.py rate-limit-status [user-id-or-ip]")
        print("    python cloud_admin.py list-rate-limits [active-only]")
        print("    python cloud_admin.py update-rate-limit <rule-name> <limit> <window-seconds>")
        print("    python cloud_admin.py create-rate-limit <rule-name> <pattern> <scope> <limit> <window-seconds>")
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

    elif command == "broadcast-command":
        if len(sys.argv) < 4:
            print("Error: filter-json and command-type required")
            return
        filter_json = json.loads(sys.argv[2])
        command_type = sys.argv[3]
        data = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        rollout_config = json.loads(sys.argv[5]) if len(sys.argv) > 5 else None
        await broadcast_command(filter_json, command_type, data, rollout_config)

    elif command == "list-broadcasts":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        await list_broadcasts(status)

    elif command == "broadcast-status":
        if len(sys.argv) < 3:
            print("Error: broadcast-id required")
            return
        await get_broadcast_status(sys.argv[2])

    elif command == "cancel-broadcast":
        if len(sys.argv) < 3:
            print("Error: broadcast-id required")
            return
        await cancel_broadcast(sys.argv[2])

    elif command == "list-templates":
        await list_templates()

    elif command == "get-template":
        if len(sys.argv) < 3:
            print("Error: template-name required")
            return
        await get_template(sys.argv[2])

    elif command == "apply-template":
        if len(sys.argv) < 4:
            print("Error: template-name and device-id required")
            return
        template_name = sys.argv[2]
        device_id = sys.argv[3]
        variables = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        await apply_template_to_device(template_name, device_id, variables)

    elif command == "apply-template-broadcast":
        if len(sys.argv) < 4:
            print("Error: template-name and filter-json required")
            return
        template_name = sys.argv[2]
        target_filter = json.loads(sys.argv[3])
        variables = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
        rollout_config = json.loads(sys.argv[5]) if len(sys.argv) > 5 else None
        await apply_template_broadcast(template_name, target_filter, variables, rollout_config)

    elif command == "create-batch":
        if len(sys.argv) < 4:
            print("Error: device-id and commands-json required")
            return
        device_id = sys.argv[2]
        commands_json = sys.argv[3]
        execution_mode = sys.argv[4] if len(sys.argv) > 4 else "sequential"
        await create_batch(device_id, commands_json, execution_mode)

    elif command == "list-batches":
        device_id = sys.argv[2] if len(sys.argv) > 2 else None
        status = sys.argv[3] if len(sys.argv) > 3 else None
        await list_batches(device_id, status)

    elif command == "batch-status":
        if len(sys.argv) < 3:
            print("Error: batch-id required")
            return
        await get_batch_status(sys.argv[2])

    elif command == "cancel-batch":
        if len(sys.argv) < 3:
            print("Error: batch-id required")
            return
        await cancel_batch(sys.argv[2])

    elif command == "create-schedule":
        if len(sys.argv) < 3:
            print("Error: schedule-json required")
            return
        await create_schedule(sys.argv[2])

    elif command == "list-schedules":
        device_id = sys.argv[2] if len(sys.argv) > 2 else None
        status = sys.argv[3] if len(sys.argv) > 3 else None
        schedule_type = sys.argv[4] if len(sys.argv) > 4 else None
        await list_schedules(device_id, status, schedule_type)

    elif command == "schedule-status":
        if len(sys.argv) < 3:
            print("Error: schedule-id required")
            return
        await get_schedule_status(sys.argv[2])

    elif command == "pause-schedule":
        if len(sys.argv) < 3:
            print("Error: schedule-id required")
            return
        await pause_schedule(sys.argv[2])

    elif command == "resume-schedule":
        if len(sys.argv) < 3:
            print("Error: schedule-id required")
            return
        await resume_schedule(sys.argv[2])

    elif command == "cancel-schedule":
        if len(sys.argv) < 3:
            print("Error: schedule-id required")
            return
        await cancel_schedule(sys.argv[2])

    elif command == "audit-query":
        start_time = sys.argv[2] if len(sys.argv) > 2 else None
        end_time = sys.argv[3] if len(sys.argv) > 3 else None
        device_id = sys.argv[4] if len(sys.argv) > 4 else None
        event_type = sys.argv[5] if len(sys.argv) > 5 else None
        limit = int(sys.argv[6]) if len(sys.argv) > 6 else 100
        await query_audit_logs(start_time, end_time, device_id, event_type, limit)

    elif command == "audit-export":
        if len(sys.argv) < 3:
            print("Error: output-file required")
            return
        output_file = sys.argv[2]
        export_format = sys.argv[3] if len(sys.argv) > 3 else "json"
        start_time = sys.argv[4] if len(sys.argv) > 4 else None
        end_time = sys.argv[5] if len(sys.argv) > 5 else None
        device_id = sys.argv[6] if len(sys.argv) > 6 else None
        await export_audit_logs(output_file, export_format, start_time, end_time, device_id)

    elif command == "audit-stats":
        start_time = sys.argv[2] if len(sys.argv) > 2 else None
        end_time = sys.argv[3] if len(sys.argv) > 3 else None
        await get_audit_stats(start_time, end_time)

    elif command == "check-authorization":
        if len(sys.argv) < 4:
            print("Error: user-id and command-type required")
            return
        user_id = sys.argv[2]
        command_type = sys.argv[3]
        device_type = sys.argv[4] if len(sys.argv) > 4 else None
        await check_authorization(user_id, command_type, device_type)

    elif command == "request-approval":
        if len(sys.argv) < 3:
            print("Error: approval-json required")
            return
        await request_approval(sys.argv[2])

    elif command == "list-approvals":
        user_id = sys.argv[2] if len(sys.argv) > 2 else None
        status = sys.argv[3] if len(sys.argv) > 3 else None
        await list_pending_approvals(user_id, status)

    elif command == "approval-status":
        if len(sys.argv) < 3:
            print("Error: approval-id required")
            return
        await get_approval_status(sys.argv[2])

    elif command == "approve-command":
        if len(sys.argv) < 4:
            print("Error: approval-id and approver-id required")
            return
        approval_id = sys.argv[2]
        approver_id = sys.argv[3]
        comment = sys.argv[4] if len(sys.argv) > 4 else None
        await approve_command(approval_id, approver_id, comment)

    elif command == "reject-command":
        if len(sys.argv) < 4:
            print("Error: approval-id and approver-id required")
            return
        approval_id = sys.argv[2]
        approver_id = sys.argv[3]
        comment = sys.argv[4] if len(sys.argv) > 4 else None
        await reject_command(approval_id, approver_id, comment)

    elif command == "rate-limit-status":
        identifier = sys.argv[2] if len(sys.argv) > 2 else None
        await get_rate_limit_status(identifier)

    elif command == "list-rate-limits":
        active_only = sys.argv[2].lower() == "true" if len(sys.argv) > 2 else None
        await list_rate_limits(active_only)

    elif command == "update-rate-limit":
        if len(sys.argv) < 5:
            print("Error: rule-name, limit, and window required")
            return
        rule_name = sys.argv[2]
        limit = int(sys.argv[3])
        window = int(sys.argv[4])
        await update_rate_limit(rule_name, limit, window)

    elif command == "create-rate-limit":
        if len(sys.argv) < 7:
            print("Error: rule-name, pattern, scope, limit, and window required")
            return
        rule_name = sys.argv[2]
        pattern = sys.argv[3]
        scope = sys.argv[4]
        limit = int(sys.argv[5])
        window = int(sys.argv[6])
        await create_rate_limit(rule_name, pattern, scope, limit, window)

    # Command Versioning
    elif command == "list-command-versions":
        command_type = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
        active_only = "--active-only" in sys.argv
        await list_command_versions(command_type, active_only)

    elif command == "get-command-version":
        if len(sys.argv) < 4:
            print("Error: command-type and version required")
            return
        command_type = sys.argv[2]
        version = sys.argv[3]
        await get_command_version(command_type, version)

    elif command == "validate-command":
        if len(sys.argv) < 5:
            print("Error: command-type, version, and data-json required")
            return
        command_type = sys.argv[2]
        version = sys.argv[3]
        data_json = sys.argv[4]
        await validate_command_data(command_type, version, data_json)

    elif command == "command-changelog":
        if len(sys.argv) < 3:
            print("Error: command-type required")
            return
        command_type = sys.argv[2]
        from_version = sys.argv[3] if len(sys.argv) > 3 else None
        to_version = sys.argv[4] if len(sys.argv) > 4 else None
        await get_command_changelog(command_type, from_version, to_version)

    # Webhook Management
    elif command == "list-webhooks":
        active_only = "--active-only" in sys.argv
        await list_webhooks(active_only)

    elif command == "get-webhook":
        if len(sys.argv) < 3:
            print("Error: webhook-id required")
            return
        webhook_id = sys.argv[2]
        await get_webhook(webhook_id)

    elif command == "create-webhook":
        if len(sys.argv) < 3:
            print("Error: webhook-json required")
            return
        webhook_json = sys.argv[2]
        await create_webhook(webhook_json)

    elif command == "update-webhook":
        if len(sys.argv) < 4:
            print("Error: webhook-id and updates-json required")
            return
        webhook_id = sys.argv[2]
        updates_json = sys.argv[3]
        await update_webhook(webhook_id, updates_json)

    elif command == "delete-webhook":
        if len(sys.argv) < 3:
            print("Error: webhook-id required")
            return
        webhook_id = sys.argv[2]
        await delete_webhook(webhook_id)

    elif command == "webhook-deliveries":
        if len(sys.argv) < 3:
            print("Error: webhook-id required")
            return
        webhook_id = sys.argv[2]
        status = sys.argv[3] if len(sys.argv) > 3 else None
        limit = int(sys.argv[4]) if len(sys.argv) > 4 else 100
        await get_webhook_deliveries(webhook_id, status, limit)

    elif command == "test-webhook":
        if len(sys.argv) < 5:
            print("Error: url, event-type, and event-data-json required")
            return
        url = sys.argv[2]
        event_type = sys.argv[3]
        event_data_json = sys.argv[4]
        secret = sys.argv[5] if len(sys.argv) > 5 else None
        await test_webhook(url, event_type, event_data_json, secret)

    else:
        print(f"Unknown command: {command}")


if __name__ == '__main__':
    asyncio.run(main())
