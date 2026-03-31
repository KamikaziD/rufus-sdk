# RUVON — Vector-Optimised Networking (COMPLETE)

## Phase 1 — Heartbeat Stagger + Per-Peer Failure Tracking
- [x] Startup jitter (0-50% interval) + per-cycle drift +/-10% in _heartbeat_loop()
- [x] 3-state circuit breaker: CLOSED / OPEN / HALF-OPEN (120s cooldown)
- [x] Per-peer stats persisted in edge_sync_state "relay_peer_stats"

## Phase 2 — Vector Scoring in MeshRouter
- [x] S(Vc) = 0.50C + 0.15/H + 0.25U + 0.10P scored relay selection
- [x] PeerStatus extended with connectivity_quality, relay_load, relay_success_rate
- [x] Greedy BFS replaced: collect all candidates, score, sort desc, attempt in order
- [x] MeshRelayMeta.vector_score=5 and relay_peer_id=6 in edge.proto + edge_pb2.py regenerated

## Phase 3 — Dynamic Peer Discovery
- [x] relay_server_url + mesh_advisory columns on edge_devices (Alembic: l7m8n9o0p1q2)
- [x] POST /api/v1/devices/{id}/relay-server + GET /api/v1/devices/{id}/mesh-peers
- [x] _register_relay_server(): outbound-route IP, idempotent (cache in edge_sync_state)
- [x] DHCP self-healing: _refresh_mesh_peers() re-registers each sync cycle (no-op if IP stable)
- [x] _get_effective_peer_urls(): cloud cache (SQLite) > static fallback

## Phase 4 — Local Master Election
- [x] _cloud_offline_secs counter; election triggers at >300s
- [x] S_lead = 0.50P + 0.25C + 0.25U (power, CPU, uptime)
- [x] POST /peer/election/claim; tie-break: lower device_id wins deterministically
- [x] _run_election(): concurrent claims, device-ID-seeded backoff (100-500ms)
- [x] _promote_to_master() / _abdicate() + persistence in edge_sync_state
- [x] Abdication on cloud reconnect in _sync_loop() and _reconnect_sync_loop()

## Phase 5 — Advisory Heartbeat + Dashboard
- [x] VectorAdvisory proto message (relay_score, connectivity_quality, known_peers, is_local_master)
- [x] HeartbeatMsg.vector_advisory = field 9; edge_pb2.py regenerated
- [x] DeviceHeartbeatRequest.vector_advisory field in api_models.py
- [x] process_heartbeat() stores advisory in edge_devices.mesh_advisory JSON column
- [x] _send_heartbeat() computes and sends vector_advisory each cycle
- [x] get_mesh_topology() includes relay_server_url, vector_score, is_local_master per node
- [x] browser_demo_2 LEADERBOARD: RUVON score breakdown (C/H/U/P), sorted by vector score
- [x] browser_demo_2 Local Master election simulated when cloudReachable=false

## Review
- [x] 241 tests pass across all 5 phases, zero regressions
