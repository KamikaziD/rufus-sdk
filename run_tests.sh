#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="/Users/kim/PycharmProjects/rufus_test/docker-compose.test-async.yml"

# ── colours ──────────────────────────────────────────────────────────────────
BOLD="\033[1m"
DIM="\033[2m"
CYAN="\033[1;36m"
GREEN="\033[1;32m"
YELLOW="\033[1;33m"
RED="\033[1;31m"
RESET="\033[0m"

# ── helpers ───────────────────────────────────────────────────────────────────
header() { echo -e "\n${CYAN}${BOLD}$*${RESET}"; }
info()   { echo -e "${DIM}  $*${RESET}"; }
ok()     { echo -e "${GREEN}  ✔  $*${RESET}"; }
warn()   { echo -e "${YELLOW}  ⚠  $*${RESET}"; }
err()    { echo -e "${RED}  ✘  $*${RESET}"; }

run() {
    echo -e "\n${DIM}▶ $*${RESET}\n"
    cd "$REPO_ROOT" && eval "$*"
}

prompt_devices() {
    read -rp "  Number of devices [default: ${1}]: " d
    echo "${d:-$1}"
}

prompt_duration() {
    read -rp "  Duration in seconds [default: ${1}]: " d
    echo "${d:-$1}"
}

prompt_workers() {
    read -rp "  Number of server workers [default: ${1}]: " w
    echo "${w:-$1}"
}

prompt_postgres() {
    local env_url="${RUFUS_POSTGRES_URL:-}"
    if [[ -n "$env_url" ]]; then
        info "Using \$RUFUS_POSTGRES_URL: $env_url"
        echo "$env_url"
        return
    fi
    read -rp "  PostgreSQL URL [leave blank to skip]: " url
    echo "$url"
}

docker_running() {
    docker compose -f "$COMPOSE_FILE" ps --services --filter status=running 2>/dev/null \
        | grep -q "rufus-server"
}

require_docker() {
    if ! docker_running; then
        warn "Docker stack does not appear to be running."
        read -rp "  Start it now? [Y/n]: " yn
        if [[ "${yn:-Y}" =~ ^[Yy]$ ]]; then
            docker compose -f "$COMPOSE_FILE" up -d
            info "Waiting for rufus-server to become healthy..."
            local attempts=0
            until docker_running || (( attempts++ >= 30 )); do sleep 2; done
            docker_running && ok "Stack is up." || { err "Stack failed to start."; exit 1; }
        else
            err "Load tests require the Docker stack. Aborting."; exit 1
        fi
    fi
}

# ── menus ─────────────────────────────────────────────────────────────────────

menu_pytest() {
    header "pytest — Unit & Integration Tests"
    echo "  1) All tests"
    echo "  2) SDK tests only"
    echo "  3) Edge tests only"
    echo "  4) CLI tests only"
    echo "  5) Provider compliance tests"
    echo "  6) Server tests only"
    echo "  7) Integration tests only"
    echo "  8) Skip integration tests (faster)"
    echo "  9) Single file  (prompted)"
    echo " 10) Single test  (prompted)"
    echo " 11) With coverage report"
    echo "  b) Back"
    echo
    read -rp "  Choice: " choice
    case "$choice" in
        1)  run "pytest" ;;
        2)  run "pytest tests/sdk/ -v" ;;
        3)  run "pytest tests/edge/ -v" ;;
        4)  run "pytest tests/cli/ -v" ;;
        5)  run "pytest tests/providers/ -v" ;;
        6)  run "pytest tests/server/ -v" ;;
        7)  run "pytest tests/integration/ -v" ;;
        8)  run "pytest -m 'not integration'" ;;
        9)
            read -rp "  File path (e.g. tests/sdk/test_engine.py): " f
            run "pytest ${f} -v"
            ;;
        10)
            read -rp "  Test path (e.g. tests/sdk/test_workflow.py::test_name): " t
            run "pytest ${t} -v"
            ;;
        11) run "pytest --cov=src --cov-report=term-missing" ;;
        b|B) return ;;
        *) warn "Unknown choice." ;;
    esac
}

menu_benchmarks() {
    header "Benchmarks"
    echo "  1) Benchmark suite — quick  (~1s)"
    echo "  2) Benchmark suite — full  (~10s)"
    echo "  3) Benchmark suite — full, JSON output"
    echo "  4) Benchmark suite — skip security sections"
    echo "  5) Workflow performance"
    echo "  6) Persistence — SQLite only"
    echo "  7) Persistence — SQLite + PostgreSQL"
    echo "  b) Back"
    echo
    read -rp "  Choice: " choice
    case "$choice" in
        1)  run "python tests/benchmarks/benchmark_suite.py --quick" ;;
        2)  run "python tests/benchmarks/benchmark_suite.py --iterations 10000" ;;
        3)  run "python tests/benchmarks/benchmark_suite.py --iterations 10000 --output json" ;;
        4)  run "python tests/benchmarks/benchmark_suite.py --quick --no-security" ;;
        5)  run "python tests/benchmarks/workflow_performance.py" ;;
        6)  run "python tests/benchmarks/persistence_benchmark.py" ;;
        7)
            pg=$(prompt_postgres)
            if [[ -n "$pg" ]]; then
                run "python tests/benchmarks/persistence_benchmark.py --postgres '${pg}'"
            else
                warn "No URL provided — running SQLite only."
                run "python tests/benchmarks/persistence_benchmark.py"
            fi
            ;;
        b|B) return ;;
        *) warn "Unknown choice." ;;
    esac
}

menu_load() {
    require_docker
    header "Load Tests"
    workers=$(prompt_workers 1)
    echo
    echo "  1) Heartbeat"
    echo "  2) SAF sync"
    echo "  3) Config polling"
    echo "  4) Cloud commands"
    echo "  5) Thundering herd  (SAF burst — all devices simultaneous)"
    echo "  6) WASM steps       (sustained throughput, real bridge dispatch)"
    echo "  7) WASM thundering herd  (local burst — target p99 < 50ms)"
    echo "  8) All scenarios in sequence"
    echo "  b) Back"
    echo
    read -rp "  Choice: " choice
    [[ "$choice" == "b" || "$choice" == "B" ]] && return

    case "$choice" in
        1)
            devices=$(prompt_devices 1000)
            duration=$(prompt_duration 600)
            run "python tests/load/run_load_test.py --scenario heartbeat --devices ${devices} --duration ${duration} --workers ${workers}"
            ;;
        2)
            devices=$(prompt_devices 500)
            run "python tests/load/run_load_test.py --scenario saf_sync --devices ${devices} --workers ${workers}"
            ;;
        3)
            devices=$(prompt_devices 1000)
            duration=$(prompt_duration 600)
            run "python tests/load/run_load_test.py --scenario config_poll --devices ${devices} --duration ${duration} --workers ${workers}"
            ;;
        4)
            devices=$(prompt_devices 500)
            duration=$(prompt_duration 600)
            run "python tests/load/run_load_test.py --scenario cloud_commands --devices ${devices} --duration ${duration} --workers ${workers}"
            ;;
        5)
            echo
            warn "Thundering herd fires ALL devices simultaneously."
            warn "For >1000 devices ensure docker-compose has max_connections=500 and pool max=100."
            echo
            devices=$(prompt_devices 1000)
            run "python tests/load/run_load_test.py --scenario thundering_herd --devices ${devices} --workers ${workers}"
            ;;
        6)
            devices=$(prompt_devices 100)
            duration=$(prompt_duration 300)
            run "python tests/load/run_load_test.py --scenario wasm_steps --devices ${devices} --duration ${duration} --workers ${workers}"
            ;;
        7)
            echo
            info "WASM dispatch is local — no HTTP, no DB. Expected p99 < 50ms."
            info "Contrast: SAF thundering herd p50 is typically ~6,000ms."
            info "Baseline (pre-Sovereign Dispatcher): p99 = 5,055ms at 50,000 devices."
            info "Target (post-Sovereign Dispatcher):  p99 < 50ms."
            echo
            devices=$(prompt_devices 1000)
            run "python tests/load/run_load_test.py --scenario wasm_thundering_herd --devices ${devices} --workers ${workers}"
            ;;
        8)
            devices=$(prompt_devices 100)
            run "python tests/load/run_load_test.py --all --devices ${devices} --workers ${workers}"
            ;;
        *) warn "Unknown choice." ;;
    esac
}

menu_docker() {
    header "Docker Stack"
    echo "  1) Start stack"
    echo "  2) Stop stack"
    echo "  3) Restart server  (pick up code changes)"
    echo "  4) Show service health"
    echo "  5) Tail server logs"
    echo "  6) Tail all logs"
    echo "  b) Back"
    echo
    read -rp "  Choice: " choice
    case "$choice" in
        1)  docker compose -f "$COMPOSE_FILE" up -d ;;
        2)  docker compose -f "$COMPOSE_FILE" down ;;
        3)  docker compose -f "$COMPOSE_FILE" restart rufus-server ;;
        4)  docker compose -f "$COMPOSE_FILE" ps ;;
        5)  docker logs test-rufus-server -f ;;
        6)  docker compose -f "$COMPOSE_FILE" logs -f ;;
        b|B) return ;;
        *) warn "Unknown choice." ;;
    esac
}

# ── main loop ─────────────────────────────────────────────────────────────────

while true; do
    echo
    echo -e "${BOLD}╔══════════════════════════════════╗${RESET}"
    echo -e "${BOLD}║       Rufus Test Runner          ║${RESET}"
    echo -e "${BOLD}╚══════════════════════════════════╝${RESET}"
    echo "  1) Unit & Integration Tests  (pytest)"
    echo "  2) Benchmarks"
    echo "  3) Load Tests"
    echo "  4) Docker Stack"
    echo "  q) Quit"
    echo
    read -rp "  Choice: " main_choice
    case "$main_choice" in
        1)  menu_pytest ;;
        2)  menu_benchmarks ;;
        3)  menu_load ;;
        4)  menu_docker ;;
        q|Q) echo; ok "Bye."; exit 0 ;;
        *)  warn "Unknown choice." ;;
    esac
done
