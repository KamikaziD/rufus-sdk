#!/bin/bash
# Quick setup script for running workflows from debugging directory

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Add to PYTHONPATH
export PYTHONPATH="$DIR:$PYTHONPATH"

echo "✅ Added $DIR to PYTHONPATH"
echo ""
echo "You can now run:"
echo "  rufus workflow start TestApplication -d '{\"name\":\"Detmar\", \"age\": 45}' --config ./test_workflow.yaml"
echo ""
echo "Or start an interactive shell with PYTHONPATH set:"
echo "  bash"
