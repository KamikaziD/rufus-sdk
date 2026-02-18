#!/bin/bash
set -e

echo "==============================================="
echo "Rufus Edge Worker - Production"
echo "==============================================="
echo "Workflow Version: ${WORKFLOW_VERSION}"
echo "Build SHA: ${BUILD_SHA}"
echo "Build Date: ${BUILD_DATE}"
echo "Worker ID: ${HOSTNAME}"
echo "==============================================="

# Verify workflows directory
if [ ! -d "$WORKFLOWS_DIR" ]; then
    echo "❌ ERROR: Workflows directory not found: $WORKFLOWS_DIR"
    exit 1
fi

WORKFLOW_COUNT=$(find "$WORKFLOWS_DIR" -name "*.yaml" | wc -l)
echo "✅ Found $WORKFLOW_COUNT workflow definitions"

# List workflows
echo ""
echo "Available workflows:"
find "$WORKFLOWS_DIR" -name "*.yaml" -exec basename {} \;

# Verify step functions are importable
echo ""
echo "Verifying step functions..."
python -c "
import importlib
import sys

# Try importing all common step modules
modules_to_check = ['my_app.steps', 'my_app.models', 'my_app.validators']

for module_name in modules_to_check:
    try:
        module = importlib.import_module(module_name)
        print(f'✅ {module_name} imported successfully')
    except ImportError as e:
        print(f'⚠️  {module_name} not found (may not be required)')
    except Exception as e:
        print(f'❌ {module_name} import failed: {e}')
        sys.exit(1)

print('')
print('✅ All required modules loaded successfully')
"

# Start health check server (for K8s probes)
echo ""
echo "Starting health check server on :8080..."
python -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import json
import os

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            # Liveness check
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'status': 'healthy',
                'version': os.getenv('WORKFLOW_VERSION', 'unknown'),
                'build_sha': os.getenv('BUILD_SHA', 'unknown')
            }).encode())

        elif self.path == '/ready':
            # Readiness check
            # TODO: Check if Celery is connected to Redis
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ready'}).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress default logging
        pass

server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
print('Health check server started on :8080')
" &

# Wait for health server to start
sleep 2

echo ""
echo "==============================================="
echo "Starting Celery worker..."
echo "==============================================="
echo ""

# Execute the CMD (Celery worker)
exec "$@"
