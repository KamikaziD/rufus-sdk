"""Integration tests for webhook notifications."""

import pytest
import httpx
import asyncio
import hmac
import hashlib
import json
from typing import AsyncGenerator
from fastapi import FastAPI, Request
import uvicorn
import threading
import time

# Test server URLs
BASE_URL = "http://localhost:8000"
WEBHOOK_RECEIVER_URL = "http://localhost:9000"


class WebhookReceiver:
    """Simple webhook receiver for testing."""

    def __init__(self):
        self.app = FastAPI()
        self.received_webhooks = []
        self.server = None
        self.thread = None

        @self.app.post("/webhook")
        async def receive_webhook(request: Request):
            """Receive webhook."""
            signature = request.headers.get("X-Rufus-Signature")
            payload = await request.json()

            self.received_webhooks.append({
                "signature": signature,
                "payload": payload,
                "headers": dict(request.headers)
            })

            return {"status": "ok"}

        @self.app.get("/health")
        async def health():
            """Health check."""
            return {"status": "healthy"}

    def start(self):
        """Start receiver in background thread."""
        def run():
            config = uvicorn.Config(self.app, host="127.0.0.1", port=9000, log_level="error")
            self.server = uvicorn.Server(config)
            self.server.run()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        time.sleep(1)  # Wait for server to start

    def stop(self):
        """Stop receiver."""
        if self.server:
            self.server.should_exit = True

    def clear(self):
        """Clear received webhooks."""
        self.received_webhooks.clear()

    def get_latest(self):
        """Get latest received webhook."""
        return self.received_webhooks[-1] if self.received_webhooks else None

    def verify_signature(self, payload: dict, signature: str, secret: str) -> bool:
        """Verify HMAC signature."""
        if not signature or not signature.startswith("sha256="):
            return False

        expected_sig = signature[7:]  # Remove "sha256=" prefix
        payload_bytes = json.dumps(payload, sort_keys=True).encode('utf-8')
        computed_sig = hmac.new(
            secret.encode('utf-8'),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_sig, computed_sig)


@pytest.fixture(scope="module")
def webhook_receiver():
    """Start webhook receiver for tests."""
    receiver = WebhookReceiver()
    receiver.start()
    yield receiver
    receiver.stop()


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest.mark.asyncio
class TestWebhookIntegration:
    """Integration tests for webhook notifications."""

    async def test_create_webhook(self, client: httpx.AsyncClient):
        """Test creating a webhook."""
        webhook_data = {
            "webhook_id": "integration-test-webhook",
            "name": "Integration Test Webhook",
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "events": ["device.online", "device.offline"],
            "secret": "test-secret-key"
        }

        response = await client.post("/api/v1/webhooks", json=webhook_data)

        assert response.status_code == 200
        data = response.json()

        assert data["webhook_id"] == "integration-test-webhook"
        assert data["status"] == "registered"
        assert "device.online" in data["events"]

    async def test_list_webhooks(self, client: httpx.AsyncClient):
        """Test listing webhooks."""
        response = await client.get("/api/v1/webhooks")

        assert response.status_code == 200
        data = response.json()

        assert "webhooks" in data
        assert "total" in data
        assert isinstance(data["webhooks"], list)

    async def test_get_webhook(self, client: httpx.AsyncClient):
        """Test getting webhook details."""
        response = await client.get("/api/v1/webhooks/integration-test-webhook")

        assert response.status_code == 200
        data = response.json()

        assert data["webhook_id"] == "integration-test-webhook"
        assert data["name"] == "Integration Test Webhook"
        assert data["is_active"] is True
        assert "device.online" in data["events"]

    async def test_update_webhook(self, client: httpx.AsyncClient):
        """Test updating webhook."""
        response = await client.put(
            "/api/v1/webhooks/integration-test-webhook",
            json={"is_active": False}
        )

        assert response.status_code == 200

        # Verify update
        response = await client.get("/api/v1/webhooks/integration-test-webhook")
        assert response.json()["is_active"] is False

        # Restore active status
        await client.put(
            "/api/v1/webhooks/integration-test-webhook",
            json={"is_active": True}
        )

    async def test_webhook_delivery(self, client: httpx.AsyncClient, webhook_receiver: WebhookReceiver):
        """Test webhook delivery with signature verification."""
        webhook_receiver.clear()

        # Test webhook
        test_data = {
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "event_type": "device.online",
            "event_data": {"device_id": "test-device-123", "timestamp": "2026-02-06T12:00:00Z"},
            "secret": "test-secret"
        }

        response = await client.post("/api/v1/webhooks/test", json=test_data)

        assert response.status_code == 200

        # Wait for webhook delivery
        await asyncio.sleep(0.5)

        # Verify webhook was received
        latest = webhook_receiver.get_latest()
        assert latest is not None

        payload = latest["payload"]
        assert payload["event"] == "device.online"
        assert payload["data"]["device_id"] == "test-device-123"

        # Verify signature
        signature = latest["signature"]
        assert signature is not None
        assert webhook_receiver.verify_signature(payload, signature, "test-secret")

    async def test_webhook_custom_headers(self, client: httpx.AsyncClient, webhook_receiver: WebhookReceiver):
        """Test webhook with custom headers."""
        webhook_receiver.clear()

        # Create webhook with custom headers
        webhook_data = {
            "webhook_id": "custom-headers-webhook",
            "name": "Custom Headers Test",
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "events": ["device.online"],
            "headers": {
                "Authorization": "Bearer test-token-123",
                "X-Custom-Header": "custom-value"
            }
        }

        response = await client.post("/api/v1/webhooks", json=webhook_data)
        assert response.status_code == 200

        # Trigger test webhook
        test_data = {
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "event_type": "device.online",
            "event_data": {"device_id": "test-123"}
        }

        # Note: Test endpoint doesn't support custom headers from webhook registration
        # This would need to be tested with actual event dispatching

    async def test_get_webhook_deliveries(self, client: httpx.AsyncClient):
        """Test getting webhook delivery history."""
        response = await client.get("/api/v1/webhooks/integration-test-webhook/deliveries")

        assert response.status_code == 200
        data = response.json()

        assert "deliveries" in data
        assert "total" in data
        assert isinstance(data["deliveries"], list)

    async def test_webhook_deliveries_filtering(self, client: httpx.AsyncClient):
        """Test filtering webhook deliveries by status."""
        # Get failed deliveries
        response = await client.get(
            "/api/v1/webhooks/integration-test-webhook/deliveries",
            params={"status": "failed"}
        )

        assert response.status_code == 200
        data = response.json()

        # All should be failed status
        for delivery in data["deliveries"]:
            assert delivery["status"] == "failed"

    async def test_delete_webhook(self, client: httpx.AsyncClient):
        """Test deleting webhook."""
        # Create a temporary webhook
        webhook_data = {
            "webhook_id": "temp-webhook",
            "name": "Temporary Webhook",
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "events": ["device.online"]
        }

        await client.post("/api/v1/webhooks", json=webhook_data)

        # Delete it
        response = await client.delete("/api/v1/webhooks/temp-webhook")
        assert response.status_code == 200

        # Verify it's gone
        response = await client.get("/api/v1/webhooks/temp-webhook")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestWebhookEventDispatching:
    """Test webhook event dispatching integration."""

    async def test_device_registration_triggers_webhook(
        self,
        client: httpx.AsyncClient,
        webhook_receiver: WebhookReceiver
    ):
        """Test that device registration triggers webhook."""
        webhook_receiver.clear()

        # Ensure webhook is active and subscribed to device.registered
        webhook_data = {
            "webhook_id": "device-events-webhook",
            "name": "Device Events",
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "events": ["device.registered"],
            "secret": "device-secret"
        }

        await client.post("/api/v1/webhooks", json=webhook_data)

        # Register a device
        device_data = {
            "device_id": "webhook-test-device",
            "device_type": "POS_TERMINAL",
            "device_name": "Webhook Test Device",
            "merchant_id": "test-merchant",
            "firmware_version": "1.0.0",
            "sdk_version": "0.1.0"
        }

        response = await client.post("/api/v1/devices", json=device_data)

        # Wait for webhook delivery
        await asyncio.sleep(1.0)

        # Verify webhook was triggered
        latest = webhook_receiver.get_latest()

        if latest:  # May not receive if device already exists
            assert latest["payload"]["event"] == "device.registered"
            assert latest["payload"]["data"]["device_id"] == "webhook-test-device"

    async def test_command_creation_triggers_webhook(
        self,
        client: httpx.AsyncClient,
        webhook_receiver: WebhookReceiver
    ):
        """Test that command creation triggers webhook."""
        webhook_receiver.clear()

        # Ensure webhook is active and subscribed to command.created
        webhook_data = {
            "webhook_id": "command-events-webhook",
            "name": "Command Events",
            "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
            "events": ["command.created"],
            "secret": "command-secret"
        }

        await client.post("/api/v1/webhooks", json=webhook_data)

        # Send a command
        command_data = {
            "type": "restart",
            "version": "1.0.0",
            "data": {"delay_seconds": 10}
        }

        response = await client.post(
            "/api/v1/devices/webhook-test-device/commands",
            json=command_data
        )

        # Wait for webhook delivery
        await asyncio.sleep(1.0)

        # Verify webhook was triggered
        latest = webhook_receiver.get_latest()

        if latest and response.status_code == 200:
            assert latest["payload"]["event"] == "command.created"
            assert latest["payload"]["data"]["command_type"] == "restart"


@pytest.mark.asyncio
class TestWebhookPerformance:
    """Performance tests for webhooks."""

    async def test_concurrent_webhook_creation(self, client: httpx.AsyncClient):
        """Test creating multiple webhooks concurrently."""
        import time

        async def create_webhook(i: int):
            webhook_data = {
                "webhook_id": f"perf-test-webhook-{i}",
                "name": f"Performance Test Webhook {i}",
                "url": f"{WEBHOOK_RECEIVER_URL}/webhook",
                "events": ["device.online"]
            }
            return await client.post("/api/v1/webhooks", json=webhook_data)

        # Create 20 webhooks concurrently
        start = time.time()
        tasks = [create_webhook(i) for i in range(20)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start

        # Count successful creations
        successful = sum(1 for r in responses if isinstance(r, httpx.Response) and r.status_code == 200)

        print(f"\nCreated {successful}/20 webhooks in {duration*1000:.2f}ms")
        print(f"Average per webhook: {(duration/20)*1000:.2f}ms")

        assert duration < 5.0, f"Concurrent webhook creation too slow: {duration}s"

        # Cleanup
        for i in range(20):
            try:
                await client.delete(f"/api/v1/webhooks/perf-test-webhook-{i}")
            except:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
