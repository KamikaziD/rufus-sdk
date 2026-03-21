# Browser Demo 2 + Edge Simulator Updates

## Tasks

- [x] Create `examples/browser_demo_2/serve.py`
- [x] Create `examples/edge_deployment/network_simulator.py`
- [x] Create `examples/browser_demo_2/worker.js`
- [x] Create `examples/browser_demo_2/index.html`
- [x] Create `examples/browser_demo_2/README.md`
- [x] Modify `examples/edge_deployment/edge_device_sim.py` (add NETWORK_CONDITION + wire simulator)
- [x] Modify `rufus_test/docker-compose.test-async.yml` (CORS, env vars, volumes)
- [x] Phase 4: Rewrite worker.js — PaymentSimulation parity with Docker edge sims
- [x] Phase 4: Update index.html — new stats labels + event log format

## Review

Phase 1-3: All done. Phases created/modified:
- browser_demo_2/: index.html, worker.js (PaymentSimulation parity), serve.py, README.md
- network_simulator.py: 7 profiles + auto-cycle + LatencyTransport httpx wrapper
- edge_device_sim.py: NETWORK_CONDITION env + _net_sim.make_client()
- docker-compose: CORS :8082, NETWORK_CONDITION env, network_simulator.py volumes

Phase 4 changes:
- worker.js: Full rewrite — generatePayment, runTransactionMonitoring (JS port of Python fraud rules),
  buildPaymentSimRecord, buildMonitoringRecord, makeSafTransactionFromPayment, drainSAF handles {txn,workflows} pairs
- Fraud scoring: same 5 POS rules + 6 ATM rules + typology mapping + logistic regression
- index.html: Stats renamed (Txns/sec, p99 payment) + 3 new rows (Approved, Declined, Risk HIGH+)
  + new log CSS classes (log-declined, log-highrisk)
