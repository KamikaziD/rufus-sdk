//! Rufus Sovereign Dispatcher
//!
//! Parallel Wasmtime batch executor for edge device fleets.
//!
//! Protocol (stdin → stdout):
//! ```json
//! // stdin
//! {
//!   "wasm_path": "/abs/path/to/component.wasm",
//!   "step_name": "execute",
//!   "sagas": [
//!     {"id": "0", "payload": "{...}"},
//!     {"id": "1", "payload": "{...}"}
//!   ]
//! }
//!
//! // stdout (results in input order)
//! {"results": ["{...}", "{...}"], "error": null}
//!
//! // stdout (on error)
//! {"results": [], "error": "human-readable message"}
//! ```
//!
//! Architecture:
//! - Compile the WASM component once (~50ms for cranelift AOT)
//! - Pre-warm N Store+Instance pairs (one per Tokio task, N = cpu_count)
//! - Shard sagas across tasks via tokio::sync::mpsc
//! - Collect results by index to preserve input order

use std::io::{self, Read, Write};
use std::sync::Arc;

use serde_json::{json, Value};
use tokio::sync::mpsc;
use wasmtime::component::{Component, Linker};
use wasmtime::{Config, Engine, Store};

/// One saga job sent to a worker task.
struct SagaJob {
    index: usize,
    payload: String,
    step_name: String,
    result_tx: mpsc::UnboundedSender<(usize, Result<String, String>)>,
}

/// Execute a single saga payload against a pre-instantiated component.
///
/// The component must export `execute(state_json: string, step_name: string) -> result<string, string>`.
fn call_component(
    store: &mut Store<()>,
    instance: &wasmtime::component::Instance,
    state_json: &str,
    step_name: &str,
) -> Result<String, String> {
    // Resolve the exported function: try canonical path first, then flat "execute"
    let exports = instance.exports(store);

    // Try "rufus:step/runner" interface first
    let execute_fn = exports
        .root()
        .instance("rufus:step/runner")
        .and_then(|mut iface| iface.func("execute"))
        .or_else(|| exports.root().func("execute"));

    let execute_fn = match execute_fn {
        Some(f) => f,
        None => {
            return Err(
                "Component does not export 'rufus:step/runner#execute' or 'execute'".to_string(),
            )
        }
    };

    // Call execute(state_json, step_name) → result<string, step-error>
    let mut results = vec![wasmtime::Val::I32(0)]; // placeholder
    execute_fn
        .call(
            store,
            &[
                wasmtime::Val::String(state_json.to_string().into()),
                wasmtime::Val::String(step_name.to_string().into()),
            ],
            &mut results,
        )
        .map_err(|e| format!("call error: {e}"))?;

    match results.into_iter().next() {
        Some(wasmtime::Val::String(s)) => Ok(s.to_string()),
        Some(other) => Err(format!("unexpected return type: {other:?}")),
        None => Err("component returned no value".to_string()),
    }
}

#[tokio::main]
async fn main() {
    // Read full stdin
    let mut input = String::new();
    io::stdin()
        .read_to_string(&mut input)
        .expect("failed to read stdin");

    let request: Value = match serde_json::from_str(&input) {
        Ok(v) => v,
        Err(e) => {
            write_error(&format!("JSON parse error: {e}"));
            return;
        }
    };

    let wasm_path = match request["wasm_path"].as_str() {
        Some(p) => p.to_string(),
        None => {
            write_error("missing wasm_path");
            return;
        }
    };

    let step_name = request["step_name"]
        .as_str()
        .unwrap_or("execute")
        .to_string();

    let sagas = match request["sagas"].as_array() {
        Some(a) => a.clone(),
        None => {
            write_error("missing sagas array");
            return;
        }
    };

    if sagas.is_empty() {
        write_result(vec![]);
        return;
    }

    // Read WASM binary
    let wasm_bytes = match std::fs::read(&wasm_path) {
        Ok(b) => b,
        Err(e) => {
            write_error(&format!("failed to read {wasm_path}: {e}"));
            return;
        }
    };

    // Build engine + compile component once (expensive ~50ms, amortised over batch)
    let mut config = Config::new();
    config.async_support(false);
    let engine = match Engine::new(&config) {
        Ok(e) => Arc::new(e),
        Err(e) => {
            write_error(&format!("engine init failed: {e}"));
            return;
        }
    };

    let component = match Component::new(&engine, &wasm_bytes) {
        Ok(c) => Arc::new(c),
        Err(e) => {
            write_error(&format!("component compile failed: {e}"));
            return;
        }
    };

    let pool_size = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .min(sagas.len());

    // Channel for results (index, Ok/Err)
    let (result_tx, mut result_rx) = mpsc::unbounded_channel::<(usize, Result<String, String>)>();

    // Channel for job distribution
    let (job_tx, _) = mpsc::channel::<SagaJob>(sagas.len() + pool_size);
    let job_tx = Arc::new(job_tx);

    // Spawn worker tasks — each gets its own Store+Instance
    let mut worker_handles = Vec::with_capacity(pool_size);
    let mut worker_txs: Vec<mpsc::Sender<SagaJob>> = Vec::with_capacity(pool_size);

    for _ in 0..pool_size {
        let (wtx, mut wrx) = mpsc::channel::<SagaJob>(sagas.len());
        worker_txs.push(wtx);

        let engine_clone = Arc::clone(&engine);
        let component_clone = Arc::clone(&component);

        let handle = tokio::spawn(async move {
            // Create Store + Instance for this worker (pre-warmed)
            let mut store = Store::new(&engine_clone, ());
            let linker = Linker::new(&engine_clone);
            let instance = match linker.instantiate(&mut store, &component_clone) {
                Ok(i) => i,
                Err(e) => {
                    // If instantiation fails, drain the channel returning errors
                    while let Some(job) = wrx.recv().await {
                        let _ = job.result_tx.send((
                            job.index,
                            Err(format!("instantiate failed: {e}")),
                        ));
                    }
                    return;
                }
            };

            while let Some(job) = wrx.recv().await {
                let result =
                    call_component(&mut store, &instance, &job.payload, &job.step_name);
                let _ = job.result_tx.send((job.index, result));
            }
        });
        worker_handles.push(handle);
    }

    // Distribute sagas round-robin across workers
    for (i, saga) in sagas.iter().enumerate() {
        let payload = saga["payload"].as_str().unwrap_or("{}").to_string();
        let job = SagaJob {
            index: i,
            payload,
            step_name: step_name.clone(),
            result_tx: result_tx.clone(),
        };
        let worker_idx = i % pool_size;
        if worker_txs[worker_idx].send(job).await.is_err() {
            write_error("worker channel closed unexpectedly");
            return;
        }
    }

    // Close worker channels so workers know they're done
    drop(worker_txs);
    drop(job_tx);
    drop(result_tx);

    // Collect results in order
    let mut results: Vec<Option<Result<String, String>>> = (0..sagas.len()).map(|_| None).collect();
    while let Some((idx, result)) = result_rx.recv().await {
        results[idx] = Some(result);
    }

    // Wait for workers to finish
    for handle in worker_handles {
        let _ = handle.await;
    }

    // Serialise: on any error, return that error; otherwise return all results
    let mut output: Vec<String> = Vec::with_capacity(sagas.len());
    for r in results {
        match r {
            Some(Ok(s)) => output.push(s),
            Some(Err(e)) => {
                write_error(&format!("saga execution error: {e}"));
                return;
            }
            None => {
                write_error("missing result for saga index");
                return;
            }
        }
    }

    write_result(output);
}

fn write_result(results: Vec<String>) {
    let out = json!({"results": results, "error": null});
    println!("{}", out);
    io::stdout().flush().ok();
}

fn write_error(msg: &str) {
    let out = json!({"results": [], "error": msg});
    eprintln!("[sovereign-dispatcher] ERROR: {msg}");
    println!("{}", out);
    io::stdout().flush().ok();
}
