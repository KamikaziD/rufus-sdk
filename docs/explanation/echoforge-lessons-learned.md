# EchoForge — Lessons Learned

Engineering and design insights recorded from live development and trading sessions. Each entry is a problem that was only discovered by running the system, not by reading the code.

---

## 1. Stale `_livePrice` During Crisis Regime

**What happened:** Stop-loss fired at $79,119 and logged `PnL=+$12.12` — a profitable "loss" sell. Stop-losses should never fire when the position is in profit.

**Root cause:** `execution_worker.js` only updated `_livePrice` from two sources: (a) order fill confirmations and (b) `execution_intent` messages from the main thread. During a Crisis regime, the main thread suppresses execution_intent (because no signals are passing the metabolic filter). If the last real fill was 2 minutes ago, `_livePrice` is frozen at that historical price. The 2.5% stop-loss threshold was met against a $76,320 stale price even though the actual market price was $79,119.

**Fix:** Route a `price_tick` message from `orderbook_worker` to `execution_worker` on every single tick — independently of signal flow. The execution worker adds a `case "price_tick": if (msg.price > 0) _livePrice = msg.price;` branch. This keeps `_livePrice` current even during extended regime blackouts.

**Lesson:** Any worker that uses price for risk calculations must receive price updates via a dedicated heartbeat path that is independent of the signal path. Never assume that signal traffic implies fresh price data.

---

## 2. `_exposureByPattern` Accumulation Drift

**What happened:** All buy signals were rejected because `REVERSION_A` showed 33.1% pattern exposure when the pattern cap was 30%, but the actual total BTC position was only 0.033 BTC (very small). The system was deadlocked — no buys could pass.

**Root cause:** `_exposureByPattern` tracked how much BTC each pattern was responsible for buying. On a buy fill, `_exposureByPattern.set(pattern_id, prev + qty)`. On a sell, it subtracted from the selling pattern. But CAP_TRIM and STOP_LOSS are aggregate sells: they use `pattern_id: "CAP_TRIM"` which has zero tracked exposure. So `_exposureByPattern.get("CAP_TRIM") = 0`, and `max(0, 0 - qty) = 0` — a no-op. With every new buy, the map grew. With every aggregate sell, it stayed the same. After a few cycles the map showed 100% of historical buy volume even though half the BTC was gone.

**Fix:** After a CAP_TRIM or STOP_LOSS fill, proportionally scale all entries in `_exposureByPattern` so their sum equals `_portfolio.btc`:
```js
const scale = actualBtc / totalTracked;
for (const [pid, qty] of _exposureByPattern) {
  _exposureByPattern.set(pid, qty * scale);
}
```

**Lesson:** Per-pattern exposure trackers built from incremental buy/sell events will drift whenever aggregate sells use a synthetic pattern ID. Either (a) maintain the tracker from portfolio state snapshots rather than event deltas, or (b) realign after every aggregate sell.

---

## 3. VPIN Alert Flood

**What happened:** During volatile periods the logs showed 40+ `VPIN > crisis` sentinel alerts per second, making the dashboard unreadable and filling IndexedDB session logs with redundant records.

**Root cause:** `_pollRingBuffer` runs every 8ms. When VPIN stays above the crisis threshold (which it can for minutes during a volatile regime), a new `sentinel_alert` was emitted on every single poll — 125 alerts per second.

**Fix:** Add `_vpinAlertLastAt` timestamp and check `now - _vpinAlertLastAt >= VPIN_ALERT_COOLDOWN_MS` (3 seconds) before emitting. At most one alert per 3 seconds regardless of how long VPIN stays elevated.

**Lesson:** Any sentinel whose trigger condition can stay true for extended periods must be throttled. The alert is about the transition into the danger state, not about being in the danger state. Once the dashboard has been notified, repeat alerts add noise without information.

---

## 4. CAP_TRIM Trigger Granularity

**What happened:** CAP_TRIM was configured to fire when total exposure exceeded the cap by 1% (`+0.01`). With a 25% cap, it only fired at 26% — by which time the position had grown far enough that the trim sold a significant amount. This was occasionally too slow to protect against rapid price moves.

**Fix:** Lowered the trigger from `+0.01` to `+0.002` (0.2% over cap). CAP_TRIM now fires at 25.2% when the cap is 25%, much closer to the intended limit.

**Lesson:** Percentage-based trigger guards need tight tolerances. A 1% overshoot sounds small but represents a disproportionate position increase on a fast-moving asset. Guard tightness should match the velocity of the thing being guarded.

---

## 5. Micro-Sell Sizing After Plan Reset

**What happened:** After calling `_endPlan()` (which resets `max_position_pct` to 1.0), sell signals started generating 0.0001 BTC minimum orders — the minimum safe quantity. The position wasn't being reduced meaningfully.

**Root cause:** `max_position_pct: 1.0` means 1% of portfolio per signal. Combined with near-zero pattern aliveness (patterns had lost aliveness from accumulated losses) and Kelly fraction near 0, the formula `availBtc × auto × (1.0/100) × conviction × kelly` collapsed to below minimum. The system was alive enough to try selling but not alive enough to sell a meaningful amount.

**Fix:** Strong bear sell floor — when `net_alpha < -0.005` AND `unrealized_pnl_norm < -0.003` (actually underwater), force `max(conviction × kelly, 0.15)` as the size multiplier. This bypasses the near-zero aliveness problem specifically for loss-cutting sells.

**Lesson:** Position-closing logic needs a minimum viable size floor that activates specifically when the system is trying to exit a losing position. A system that can enter a position but can only exit in tiny increments is a trap.

---

## 6. CAP_TRIM Is the Primary Alpha Source

**What happened:** After fixing the above bugs, the session produced `+$82.49` total PnL with a 38% win rate. Nearly all of the PnL (+$72.79) came from CAP_TRIM sells, not from individual pattern fills.

**Why this worked:** The effective strategy was:
1. Patterns detect momentum and buy in small increments
2. Total position accumulates to 25% cap
3. CAP_TRIM fires at 25.2%, trims to 17.5%, crystallises gains on the whole position
4. Repeat

Individual pattern win rate (38%) is below 50%, but EV is positive because wins (CAP_TRIM) are large relative to losses (individual micro-sells when patterns fade). The system essentially built a momentum accumulation + cap-driven profit-taking loop.

**Lesson:** The cap mechanism is not just a risk control — it is a position management strategy. Setting the cap too high or the trim target too conservatively destroys this effect. The 70% trim target (selling to 70% of cap, not to 0%) is load-bearing; trimming to zero would reset aliveness and cut off the momentum ride prematurely.

---

## 7. VPIN Calibration Saturation

**What happened:** After a noisy early session with many VPIN=1.0 samples (full one-directional flow), the calibration wizard set crisis threshold at 0.85 instead of 0.70. The calibration was done against p75/p95 of early-session data that was dominated by saturation events.

**Root cause:** VPIN is bounded at 1.0 by definition. An early session with a large price move produces many samples at exactly 1.0. P95 of a distribution with a floor at 1.0 is just 1.0, which skews the percentile-based calibration toward very high thresholds.

**Fix (operational):** Calibrate after at least 30 minutes of mixed market conditions. If the calibration output is > 0.80 for the crisis threshold, suspect saturation and manually inspect the VPIN histogram before accepting it.

**Lesson:** VPIN calibration data must be representative of the full distribution, not just the session-open period. Pre-session volatility spikes (price discovery after hours) will saturate the calibration.

---

## 8. Pain Map Gossip Prevents Swarm-Wide Pattern Lock

**What happened (anticipated):** Without pain map gossip, multiple nodes in the same regime could simultaneously discover that REVERSION_A is unprofitable — but each node would keep running the same pattern until its own aliveness decayed below threshold. With 3 nodes, each node's aliveness decays independently, so all three might each take 5–10 losing trades before aliveness dies.

**Design rationale for pain maps:** Pain map gossip short-circuits this by broadcasting `{pattern_id, regime_tag, trigger_vpin, hurdle_miss_pct}` when a signal drops under high VPIN. Receiving nodes apply an immediate preemptive penalty rather than waiting for their own losses to drive aliveness down. Three nodes experiencing pain in the same pattern simultaneously triggers a quorum veto — all three stop routing that pattern within seconds instead of minutes.

**Lesson:** Bayesian decay works well for individual learning but is slow for swarm-level convergence. Gossip about failure events accelerates collective learning without sharing position or capital data. The key design constraint is that pain maps must be anonymised (no quantities, no prices, no balances) — only regime context and trigger conditions.

---

## 9. Kelly Fraction + Position Sizing Interaction

**What happened:** Early sessions used `conviction × kelly` as the position size multiplier with no minimum. In strong bull trends, patterns with high `p_up` (0.85+) and high aliveness would calculate Kelly fractions near 40% (cap) — but `conviction = pow(net_aliveness, 1.5)` was 0.95 for a fully alive pattern. Combined with `max_position_pct: 0.5`, this produced large buys that could consume the entire cap in one signal.

**Design refinement:** `conviction = pow(net_aliveness, 1.5)` means near-dead patterns (aliveness 0.32) produce conviction ≈ 0.18, limiting their position impact without stopping them entirely. This is intentional — low-aliveness patterns are still allowed to "try" at reduced size. The `pow(..., 1.5)` exponent creates a smooth continuum from near-zero to full-size rather than a binary threshold.

**Lesson:** The Kelly formula assumes independent bets with known probabilities. In practice, `p_up` from the ONNX model is a noisy estimate and patterns are correlated. The 40% Kelly cap and the conviction multiplier together act as a practical risk limiter that compensates for model uncertainty. Never run raw Kelly without caps in a live system.

---

## 10. Regime-Specific Strategy Asymmetry (Nociceptor)

**What happened:** Early testing showed momentum patterns being suppressed during HighVol regime even when VPIN was directional (strong one-sided flow = momentum tailwind). This was a false positive — VPIN was high because momentum was real, not because flow was toxic.

**Fix (design):** The metabolic hurdle formula uses `strategy_type` to invert the VPIN multiplier for momentum patterns:
- Mean reversion: `1 + vpin_over × 8` — toxic flow is exactly what kills mean-reversion (the momentum blows through the spread)
- Momentum: `max(0.5, 1 - vpin_over × 2)` — toxic flow is actually a tailwind; hurdle is eased, not raised
- Arb: `1.0` — market-neutral; VPIN is irrelevant

**Lesson:** VPIN is not uniformly bad. It is specifically bad for mean-reversion strategies (informed directional flow means the reversion bet is wrong). For momentum strategies it is a confirmation signal. Any system that treats VPIN as a universal risk-off signal will incorrectly suppress the best momentum entries.
