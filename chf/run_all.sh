#!/usr/bin/env bash
# CHF — Full Pipeline Runner (thin wrapper)
# =========================================
# main.py is the single canonical entry point. It runs the DAG stage by stage
# with inter-stage verify gates already built in, so this script just delegates.
#
# Usage: ./run_all.sh [--demo]
#   --demo    Generate synthetic demo data instead of running the live pipeline

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "CHF — Full Pipeline Runner"
echo "Python: $(python3 --version)"
echo "========================================"

for arg in "$@"; do
    if [ "$arg" = "--demo" ]; then
        echo "[demo] Generating synthetic demo data..."
        python3 main.py demo
        echo ""
        echo "Demo data generated. Launch dashboard with:"
        echo "  streamlit run app/dashboard.py"
        exit 0
    fi
done

# Full pipeline: universe -> market -> onchain -> features -> labels ->
# models -> portfolio -> backtest, with verify gates between stages.
python3 main.py full

echo "========================================"
echo "Pipeline complete!"
echo "  streamlit run app/dashboard.py   # Launch dashboard"
echo "========================================"
