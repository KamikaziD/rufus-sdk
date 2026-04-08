"""
edge_admin_tool.py — Interactive host-side CLI for Ruvon Edge management.

Runs on the host machine against http://localhost:8000 (or --server override).
No authentication required — require_admin dev-mode bypass is active.

Usage:
    python examples/edge_deployment/edge_admin_tool.py [--server http://localhost:8000]

Menu:
    [1] List registered devices
    [2] Show device config
    [3] List workflow definitions
    [4] Edit + push workflow YAML
    [5] Broadcast workflow update to device(s)
    [6] Show device heartbeat / metrics
    [q] Quit
"""

import argparse
import json
import os
import subprocess
import tempfile

import httpx

BASE = "http://localhost:8000"


def _client(server: str) -> httpx.Client:
    return httpx.Client(base_url=server, timeout=15)


def list_devices(server: str):
    with _client(server) as c:
        r = c.get("/api/v1/devices")
        r.raise_for_status()
    data = r.json()
    rows = data if isinstance(data, list) else data.get("devices", [])
    print(f"\n{'DEVICE_ID':<25} {'TYPE':<10} {'STATUS':<10} {'LAST_HEARTBEAT'}")
    print("─" * 70)
    for d in rows:
        print(
            f"{d['device_id']:<25} {d.get('device_type', '?'):<10} "
            f"{d.get('status', '?'):<10} {d.get('last_heartbeat_at', '—')}"
        )


def show_device_config(server: str, device_id: str):
    with _client(server) as c:
        r = c.get(
            f"/api/v1/devices/{device_id}/config",
            headers={"X-API-Key": os.getenv("RUVON_API_KEY", "dev")},
        )
    print(json.dumps(r.json(), indent=2))


def list_workflow_definitions(server: str):
    with _client(server) as c:
        r = c.get("/api/v1/admin/workflow-definitions")
        r.raise_for_status()
    data = r.json()
    defs = data if isinstance(data, list) else data.get("definitions", [])
    print(f"\n{'WORKFLOW_TYPE':<30} {'VERSION':<10} {'UPDATED_AT'}")
    print("─" * 70)
    for d in defs:
        print(
            f"{d['workflow_type']:<30} {d.get('version', '?'):<10} "
            f"{d.get('updated_at', '—')}"
        )


def edit_and_push_workflow(server: str, workflow_type: str):
    """Download YAML → open $EDITOR → upload patch."""
    with _client(server) as c:
        r = c.get(f"/api/v1/admin/workflow-definitions/{workflow_type}")

    if r.status_code == 404:
        print(f"No server-side definition for '{workflow_type}'.")
        print("Tip: you can still broadcast via option [5] using a local YAML file.")
        return

    r.raise_for_status()
    yaml_content = r.json().get("yaml_content", "")

    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name

    editor = os.getenv("EDITOR", "vi")
    subprocess.run([editor, tmp])

    with open(tmp) as f:
        new_yaml = f.read()
    os.unlink(tmp)

    with _client(server) as c:
        r = c.patch(
            f"/api/v1/admin/workflow-definitions/{workflow_type}",
            json={"yaml_content": new_yaml},
        )
        r.raise_for_status()
    print(f"✓ Pushed updated '{workflow_type}' to server.")


def broadcast_workflow_update(server: str, workflow_type: str, yaml_content: str):
    payload = {
        "command_type": "update_workflow",
        "command_data": {
            "workflow_type": workflow_type,
            "yaml_content": yaml_content,
            "version": "pushed",
        },
    }
    with _client(server) as c:
        r = c.post("/api/v1/devices/commands/broadcast", json=payload)
        r.raise_for_status()
    result = r.json()
    print(f"✓ Broadcast queued — {result.get('queued', '?')} device(s) targeted.")


def show_device_heartbeat(server: str, device_id: str):
    with _client(server) as c:
        r = c.get(f"/api/v1/devices/{device_id}")
    print(json.dumps(r.json(), indent=2))


def main():
    parser = argparse.ArgumentParser(description="Ruvon Edge Admin Tool")
    parser.add_argument("--server", default=BASE, help="Rufus server URL")
    args = parser.parse_args()
    server = args.server.rstrip("/")

    while True:
        print(f"\n╔════════════════════════════════╗")
        print(f"║  Ruvon Edge Admin              ║")
        print(f"║  {server[:28]:<28}  ║")
        print(f"╠════════════════════════════════╣")
        print(f"║ [1] List devices               ║")
        print(f"║ [2] Show device config         ║")
        print(f"║ [3] List workflow definitions  ║")
        print(f"║ [4] Edit + push workflow YAML  ║")
        print(f"║ [5] Broadcast workflow update  ║")
        print(f"║ [6] Show device heartbeat      ║")
        print(f"║ [q] Quit                       ║")
        print(f"╚════════════════════════════════╝")
        choice = input("Select: ").strip().lower()

        if choice == "1":
            list_devices(server)
        elif choice == "2":
            did = input("Device ID: ").strip()
            show_device_config(server, did)
        elif choice == "3":
            list_workflow_definitions(server)
        elif choice == "4":
            wt = input("Workflow type (e.g. EdgeTelemetry): ").strip()
            edit_and_push_workflow(server, wt)
        elif choice == "5":
            wt = input("Workflow type: ").strip()
            yaml_path = input(
                "Path to local YAML file (or Enter to pull from server): "
            ).strip()
            if yaml_path and os.path.exists(yaml_path):
                with open(yaml_path) as f:
                    yaml_content = f.read()
            else:
                with _client(server) as c:
                    r = c.get(f"/api/v1/admin/workflow-definitions/{wt}")
                yaml_content = (
                    r.json().get("yaml_content", "") if r.status_code == 200 else ""
                )
            if yaml_content:
                broadcast_workflow_update(server, wt, yaml_content)
            else:
                print("No YAML content found — provide a local file path.")
        elif choice == "6":
            did = input("Device ID: ").strip()
            show_device_heartbeat(server, did)
        elif choice == "q":
            break
        else:
            print("Unknown option.")


if __name__ == "__main__":
    main()
