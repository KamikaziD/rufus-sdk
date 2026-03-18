/// fraud_scorer — Logistic regression fraud scoring for Rufus edge devices.
///
/// Compiled to wasm32-wasip1 (~150 KB stripped). Invoked via Wasmtime WASI.
///
/// WASI contract:
///   stdin  → JSON object with "features" (dict) and "device_type" (str)
///   stdout → JSON object with "ml_risk_score", "ml_confidence", "anomaly_features"
///   exit 0 on success; non-zero on error
///
/// Feature weights (logistic regression, calibrated for fintech fraud patterns):
///   logit = 1.2 * normalized_amount
///         + 2.5 * velocity_normalized
///         + 1.8 * time_risk
///         + 1.5 * merchant_novelty
///         + 3.0 * rules_signal
///         - 2.5  (bias)
///
/// Build:
///   rustup target add wasm32-wasip1
///   cargo build --target wasm32-wasip1 --release
///   cp target/wasm32-wasip1/release/fraud-scorer.wasm ../fraud_scorer.wasm
use std::io::{self, Read, Write};

use serde::{Deserialize, Serialize};
use serde_json::Value;

// ─────────────────────────────────────────────────────────────────────────────
// I/O structs
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
struct Input {
    features: Features,
    #[serde(default)]
    device_type: String,
}

#[derive(Deserialize)]
struct Features {
    #[serde(default)]
    normalized_amount: f64,
    #[serde(default)]
    velocity_normalized: f64,
    #[serde(default)]
    time_risk: f64,
    #[serde(default)]
    merchant_novelty: f64,
    #[serde(default)]
    rules_signal: f64,
}

#[derive(Serialize)]
struct Output {
    ml_risk_score: f64,
    ml_confidence: f64,
    anomaly_features: Vec<String>,
}

// ─────────────────────────────────────────────────────────────────────────────
// Logistic regression
// ─────────────────────────────────────────────────────────────────────────────

fn sigmoid(x: f64) -> f64 {
    1.0 / (1.0 + (-x).exp())
}

fn score(f: &Features) -> f64 {
    let logit = 1.2 * f.normalized_amount
        + 2.5 * f.velocity_normalized
        + 1.8 * f.time_risk
        + 1.5 * f.merchant_novelty
        + 3.0 * f.rules_signal
        - 2.5;
    sigmoid(logit)
}

fn anomaly_features(f: &Features) -> Vec<String> {
    let mut out = Vec::new();
    if f.normalized_amount > 0.8 {
        out.push("near_floor_limit".to_string());
    }
    if f.velocity_normalized > 0.4 {
        out.push("high_velocity".to_string());
    }
    if f.merchant_novelty > 0.5 {
        out.push("unknown_merchant".to_string());
    }
    if f.rules_signal > 0.4 {
        out.push("multiple_rules_fired".to_string());
    }
    if f.time_risk > 0.5 {
        out.push("after_hours".to_string());
    }
    out
}

// ─────────────────────────────────────────────────────────────────────────────
// Entry point
// ─────────────────────────────────────────────────────────────────────────────

fn main() {
    // Read JSON from stdin
    let mut raw = String::new();
    io::stdin()
        .read_to_string(&mut raw)
        .expect("failed to read stdin");

    let input: Input = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("fraud-scorer: JSON parse error: {}", e);
            std::process::exit(1);
        }
    };

    let risk_score = score(&input.features);
    let confidence = (risk_score - 0.5).abs() * 2.0;
    let anomaly = anomaly_features(&input.features);

    // Round to 4 decimal places
    let result = Output {
        ml_risk_score: (risk_score * 10000.0).round() / 10000.0,
        ml_confidence: (confidence * 10000.0).round() / 10000.0,
        anomaly_features: anomaly,
    };

    let out = serde_json::to_string(&result).expect("serialisation failed");
    io::stdout()
        .write_all(out.as_bytes())
        .expect("failed to write stdout");
}
