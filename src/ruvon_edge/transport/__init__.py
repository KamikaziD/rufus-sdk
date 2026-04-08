"""
EdgeTransport factory.

Returns NATSEdgeTransport when RUVON_NATS_URL is set (or nats_url is passed),
otherwise returns HTTPEdgeTransport.
"""
import os
from typing import Optional

from ruvon_edge.transport.base import EdgeTransport
from ruvon_edge.transport.http_transport import HTTPEdgeTransport


def create_transport(
    device_id: str,
    cloud_url: str,
    api_key: str,
    nats_url: Optional[str] = None,
    nats_credentials: Optional[str] = None,
) -> EdgeTransport:
    """
    Instantiate the appropriate transport based on configuration.

    Args:
        device_id: Edge device identifier
        cloud_url: Cloud control plane base URL (used by HTTP transport)
        api_key: Authentication key
        nats_url: NATS server URL (e.g. "nats://localhost:4222"). When provided,
                  NATSEdgeTransport is returned. Also read from RUVON_NATS_URL env.
        nats_credentials: Optional path to NATS credentials file (NKey/JWT).

    Returns:
        NATSEdgeTransport if nats_url is set, else HTTPEdgeTransport.
    """
    resolved_nats_url = nats_url or os.getenv("RUVON_NATS_URL")

    if resolved_nats_url:
        from ruvon_edge.transport.nats_transport import NATSEdgeTransport
        return NATSEdgeTransport(
            device_id=device_id,
            nats_url=resolved_nats_url,
            api_key=api_key,
            nats_credentials=nats_credentials or os.getenv("RUVON_NATS_CREDENTIALS"),
        )

    return HTTPEdgeTransport(
        device_id=device_id,
        cloud_url=cloud_url,
        api_key=api_key,
    )


__all__ = ["EdgeTransport", "HTTPEdgeTransport", "create_transport"]
