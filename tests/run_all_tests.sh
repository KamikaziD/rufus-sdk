#!/bin/bash
# Run all integration and load tests for Rufus Edge Cloud Control Plane

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================================================${NC}"
echo -e "${BLUE}  Rufus Edge Cloud Control Plane - Test Suite${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo ""

# Check if server is running
echo -e "${YELLOW}Checking if server is running...${NC}"
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Server is running${NC}"
else
    echo -e "${RED}✗ Server is not running!${NC}"
    echo ""
    echo "Please start the server first:"
    echo "  uvicorn rufus_server.main:app --reload"
    echo ""
    exit 1
fi

# Check database connection
echo -e "${YELLOW}Checking database connection...${NC}"
if [ -z "$DATABASE_URL" ]; then
    echo -e "${YELLOW}! DATABASE_URL not set, using default (SQLite)${NC}"
else
    echo -e "${GREEN}✓ DATABASE_URL configured${NC}"
fi

echo ""

# Run integration tests
echo -e "${BLUE}========================================================================${NC}"
echo -e "${BLUE}  Integration Tests${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo ""

echo -e "${YELLOW}Running command versioning integration tests...${NC}"
pytest tests/integration/test_command_versioning_integration.py -v --tb=short

echo ""
echo -e "${YELLOW}Running webhook integration tests...${NC}"
pytest tests/integration/test_webhook_integration.py -v --tb=short

echo ""
echo -e "${YELLOW}Running webhook retry integration tests...${NC}"
pytest tests/integration/test_webhook_retry_integration.py -v --tb=short

echo ""

# Run load tests
echo -e "${BLUE}========================================================================${NC}"
echo -e "${BLUE}  Load Tests${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo ""

echo -e "${YELLOW}Running load test suite...${NC}"
python tests/load/load_test_suite.py

echo ""

# Summary
echo -e "${BLUE}========================================================================${NC}"
echo -e "${GREEN}  All Tests Completed!${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo ""

echo "Summary:"
echo "  ✓ Integration tests passed"
echo "  ✓ Load tests completed"
echo ""

echo "Next steps:"
echo "  1. Review load test results above"
echo "  2. Check for any performance bottlenecks"
echo "  3. Optimize slow endpoints if needed"
echo ""
