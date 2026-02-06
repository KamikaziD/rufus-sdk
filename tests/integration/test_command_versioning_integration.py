"""Integration tests for command versioning."""

import pytest
import httpx
import asyncio
from typing import AsyncGenerator

# Test server URL
BASE_URL = "http://localhost:8000"


@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create async HTTP client."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield client


@pytest.mark.asyncio
class TestCommandVersioningIntegration:
    """Integration tests for command versioning API."""

    async def test_list_command_versions(self, client: httpx.AsyncClient):
        """Test listing all command versions."""
        response = await client.get("/api/v1/commands/versions")

        assert response.status_code == 200
        data = response.json()

        assert "versions" in data
        assert "total" in data
        assert isinstance(data["versions"], list)

        # Should have seed data (restart, health_check, update_firmware, clear_cache)
        assert data["total"] >= 4

        # Verify version structure
        if data["versions"]:
            version = data["versions"][0]
            assert "command_type" in version
            assert "version" in version
            assert "is_active" in version

    async def test_get_latest_version(self, client: httpx.AsyncClient):
        """Test getting latest version for a command type."""
        response = await client.get("/api/v1/commands/restart/versions/latest")

        assert response.status_code == 200
        data = response.json()

        assert data["command_type"] == "restart"
        assert data["version"] == "1.0.0"
        assert data["is_active"] is True
        assert "schema_definition" in data

    async def test_validate_valid_command(self, client: httpx.AsyncClient):
        """Test validating valid command data."""
        response = await client.post(
            "/api/v1/commands/restart/validate",
            json={
                "version": "1.0.0",
                "data": {"delay_seconds": 10}
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is True
        assert len(data["errors"]) == 0

    async def test_validate_invalid_command_oversized(self, client: httpx.AsyncClient):
        """Test validating invalid command (value too large)."""
        response = await client.post(
            "/api/v1/commands/restart/validate",
            json={
                "version": "1.0.0",
                "data": {"delay_seconds": 500}  # Max is 300
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert len(data["errors"]) > 0
        assert "300" in data["errors"][0]  # Should mention max value

    async def test_validate_invalid_command_wrong_type(self, client: httpx.AsyncClient):
        """Test validating invalid command (wrong type)."""
        response = await client.post(
            "/api/v1/commands/restart/validate",
            json={
                "version": "1.0.0",
                "data": {"delay_seconds": "abc"}  # Should be integer
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert len(data["errors"]) > 0

    async def test_validate_update_firmware_missing_required(self, client: httpx.AsyncClient):
        """Test validating update_firmware without required field."""
        response = await client.post(
            "/api/v1/commands/update_firmware/validate",
            json={
                "version": "1.0.0",
                "data": {"url": "https://example.com/fw.bin"}  # Missing required 'version'
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert data["valid"] is False
        assert len(data["errors"]) > 0
        assert "version" in data["errors"][0].lower()

    async def test_validate_clear_cache_enum(self, client: httpx.AsyncClient):
        """Test validating clear_cache with enum values."""
        # Valid enum value
        response = await client.post(
            "/api/v1/commands/clear_cache/validate",
            json={
                "version": "1.0.0",
                "data": {"cache_type": "all"}
            }
        )

        assert response.status_code == 200
        assert response.json()["valid"] is True

        # Invalid enum value
        response = await client.post(
            "/api/v1/commands/clear_cache/validate",
            json={
                "version": "1.0.0",
                "data": {"cache_type": "invalid"}
            }
        )

        assert response.status_code == 200
        assert response.json()["valid"] is False

    async def test_send_command_with_validation(self, client: httpx.AsyncClient):
        """Test sending command with automatic validation."""
        # First register a test device
        device_data = {
            "device_id": "integration-test-device",
            "device_type": "TEST_DEVICE",
            "device_name": "Integration Test Device",
            "merchant_id": "test-merchant",
            "firmware_version": "1.0.0",
            "sdk_version": "0.1.0"
        }

        # Register device (may already exist, ignore 500 error)
        try:
            await client.post("/api/v1/devices", json=device_data)
        except:
            pass

        # Send valid command
        response = await client.post(
            "/api/v1/devices/integration-test-device/commands",
            json={
                "type": "restart",
                "version": "1.0.0",
                "data": {"delay_seconds": 10}
            }
        )

        # Should succeed (200 or 404 if device doesn't exist)
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert "command_id" in data

    async def test_send_command_with_invalid_data(self, client: httpx.AsyncClient):
        """Test sending command with invalid data (should fail validation)."""
        # Send invalid command
        response = await client.post(
            "/api/v1/devices/integration-test-device/commands",
            json={
                "type": "restart",
                "version": "1.0.0",
                "data": {"delay_seconds": 500}  # Invalid: > 300
            }
        )

        # Should fail validation
        assert response.status_code in [400, 404]  # 400 for validation error, 404 if device not found

    async def test_list_versions_filtering(self, client: httpx.AsyncClient):
        """Test filtering versions by command type."""
        response = await client.get(
            "/api/v1/commands/versions",
            params={"command_type": "restart"}
        )

        assert response.status_code == 200
        data = response.json()

        # All versions should be for 'restart'
        for version in data["versions"]:
            assert version["command_type"] == "restart"

    async def test_list_versions_active_only(self, client: httpx.AsyncClient):
        """Test filtering active versions only."""
        response = await client.get(
            "/api/v1/commands/versions",
            params={"is_active": "true"}
        )

        assert response.status_code == 200
        data = response.json()

        # All versions should be active
        for version in data["versions"]:
            assert version["is_active"] is True

    async def test_changelog_endpoint(self, client: httpx.AsyncClient):
        """Test getting command changelog."""
        response = await client.get("/api/v1/commands/restart/changelog")

        assert response.status_code == 200
        data = response.json()

        assert "changelog" in data
        assert "total_entries" in data
        assert isinstance(data["changelog"], list)


@pytest.mark.asyncio
class TestCommandVersioningPerformance:
    """Performance tests for command versioning."""

    async def test_validation_performance(self, client: httpx.AsyncClient):
        """Test validation performance (should be fast with caching)."""
        import time

        # First validation (cold cache)
        start = time.time()
        response = await client.post(
            "/api/v1/commands/restart/validate",
            json={
                "version": "1.0.0",
                "data": {"delay_seconds": 10}
            }
        )
        cold_time = time.time() - start

        assert response.status_code == 200

        # Second validation (warm cache)
        start = time.time()
        response = await client.post(
            "/api/v1/commands/restart/validate",
            json={
                "version": "1.0.0",
                "data": {"delay_seconds": 20}
            }
        )
        warm_time = time.time() - start

        assert response.status_code == 200

        # Warm cache should be faster or similar
        print(f"\nValidation Performance:")
        print(f"  Cold cache: {cold_time*1000:.2f}ms")
        print(f"  Warm cache: {warm_time*1000:.2f}ms")

        # Both should be reasonably fast (< 100ms)
        assert cold_time < 0.1, f"Cold cache validation too slow: {cold_time}s"
        assert warm_time < 0.1, f"Warm cache validation too slow: {warm_time}s"

    async def test_concurrent_validations(self, client: httpx.AsyncClient):
        """Test concurrent validation requests."""
        import time

        async def validate():
            return await client.post(
                "/api/v1/commands/restart/validate",
                json={
                    "version": "1.0.0",
                    "data": {"delay_seconds": 10}
                }
            )

        # Run 50 concurrent validations
        start = time.time()
        tasks = [validate() for _ in range(50)]
        responses = await asyncio.gather(*tasks)
        duration = time.time() - start

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

        # Should complete in reasonable time
        print(f"\n50 concurrent validations: {duration*1000:.2f}ms")
        print(f"Average per request: {(duration/50)*1000:.2f}ms")

        assert duration < 2.0, f"Concurrent validations too slow: {duration}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
