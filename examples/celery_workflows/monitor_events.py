#!/usr/bin/env python
"""
Real-time event monitor for workflow events.

Monitors Redis streams and displays workflow events as they occur.
"""
import asyncio
import os
import sys
import redis.asyncio as redis
from datetime import datetime


async def monitor_events():
    """Monitor workflow events from Redis streams."""
    redis_url = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

    print("="*70)
    print(" WORKFLOW EVENT MONITOR")
    print("="*70)
    print(f"Monitoring: {redis_url}")
    print("Press Ctrl+C to stop")
    print("="*70 + "\n")

    try:
        r = redis.from_url(redis_url, decode_responses=True)

        # Start from the beginning or last ID
        last_id = "0"

        while True:
            # Read events from workflow:persistence stream
            events = await r.xread(
                {'workflow:persistence': last_id},
                count=10,
                block=1000  # Block for 1 second
            )

            for stream_name, messages in events:
                for message_id, data in messages:
                    last_id = message_id

                    # Parse event data
                    event_type = data.get('event_type', 'unknown')
                    timestamp = float(data.get('timestamp', 0))
                    dt = datetime.fromtimestamp(timestamp)

                    # Color-code by event type
                    if 'created' in event_type:
                        emoji = "🆕"
                        color = "\033[92m"  # Green
                    elif 'completed' in event_type:
                        emoji = "✅"
                        color = "\033[94m"  # Blue
                    elif 'failed' in event_type:
                        emoji = "❌"
                        color = "\033[91m"  # Red
                    elif 'updated' in event_type:
                        emoji = "🔄"
                        color = "\033[93m"  # Yellow
                    else:
                        emoji = "📝"
                        color = "\033[0m"   # Default

                    # Print event
                    print(f"{color}{emoji} [{dt.strftime('%H:%M:%S')}] {event_type}\033[0m")

                    # Print payload details
                    payload_str = data.get('payload', '{}')
                    try:
                        import json
                        payload = json.loads(payload_str)
                        if 'id' in payload:
                            print(f"   Workflow ID: {payload['id']}")
                        if 'status' in payload:
                            print(f"   Status: {payload['status']}")
                        if 'workflow_type' in payload:
                            print(f"   Type: {payload['workflow_type']}")
                    except:
                        pass

                    print()

            # Brief pause before next iteration
            await asyncio.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await r.close()


if __name__ == "__main__":
    asyncio.run(monitor_events())
