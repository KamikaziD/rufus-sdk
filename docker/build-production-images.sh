#!/bin/bash
# Build and push production Rufus images for linux/amd64 + linux/arm64
# These images install ruvon-sdk from PyPI instead of copying source
#
# Usage:
#   ./build-production-images.sh [VERSION] [REGISTRY] [PUSH=true|false]
#   ./build-production-images.sh 0.6.3 ruhfuskdev true

set -e

# Configuration
VERSION="${1:-1.0.0-rc1}"
REGISTRY="${2:-ruhfuskdev}"
PUSH="${3:-false}"
PLATFORMS="linux/amd64,linux/arm64"

echo "=========================================="
echo "  Building Rufus Production Images"
echo "=========================================="
echo "Version:   $VERSION"
echo "Registry:  $REGISTRY"
echo "Platforms: $PLATFORMS"
echo "Push:      $PUSH"
echo ""

# Ensure a buildx builder with multi-platform support exists
if ! docker buildx inspect ruvon-builder &>/dev/null; then
    echo "Creating multi-platform buildx builder..."
    docker buildx create --name ruvon-builder --driver docker-container --bootstrap --use
else
    docker buildx use ruvon-builder
fi

# buildx always needs --push or --load; use --push when PUSH=true, --load otherwise.
# Note: --load only works for single-platform (use amd64 for local testing).
if [ "$PUSH" = "true" ]; then
    BUILD_OUTPUT="--push"
    BUILD_PLATFORMS="--platform ${PLATFORMS}"
else
    # Local load only supports a single platform
    BUILD_OUTPUT="--load"
    BUILD_PLATFORMS="--platform linux/amd64"
    echo "Note: local --load only supports linux/amd64. Use PUSH=true for multi-arch."
    echo ""
fi

echo "Building ruvon-server..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.ruvon-server-prod \
    -t ${REGISTRY}/ruvon-server:${VERSION} \
    -t ${REGISTRY}/ruvon-server:latest \
    ..

echo "Building ruvon-worker..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.ruvon-worker-prod \
    -t ${REGISTRY}/ruvon-worker:${VERSION} \
    -t ${REGISTRY}/ruvon-worker:latest \
    ..

echo "Building ruvon-flower..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.ruvon-flower-prod \
    -t ${REGISTRY}/ruvon-flower:${VERSION} \
    -t ${REGISTRY}/ruvon-flower:latest \
    ..

echo "Building ruvon-dashboard..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.ruvon-dashboard-prod \
    -t ${REGISTRY}/ruvon-dashboard:${VERSION} \
    -t ${REGISTRY}/ruvon-dashboard:latest \
    ..

echo ""
echo "Build complete!"
echo ""

if [ "$PUSH" = "true" ]; then
    echo "Images pushed to Docker Hub:"
    echo "  - ${REGISTRY}/ruvon-server:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-server:latest"
    echo "  - ${REGISTRY}/ruvon-worker:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-worker:latest"
    echo "  - ${REGISTRY}/ruvon-flower:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-flower:latest"
    echo "  - ${REGISTRY}/ruvon-dashboard:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-dashboard:latest"
    echo ""
    echo "Verify multi-arch manifests:"
    echo "  docker buildx imagetools inspect ${REGISTRY}/ruvon-server:${VERSION}"
else
    echo "Images loaded locally (linux/amd64 only):"
    echo "  - ${REGISTRY}/ruvon-server:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-worker:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-flower:${VERSION}"
    echo "  - ${REGISTRY}/ruvon-dashboard:${VERSION}"
    echo ""
    echo "To build and push multi-arch:"
    echo "  ./build-production-images.sh $VERSION $REGISTRY true"
fi

echo ""
echo "=========================================="
echo "  Next Steps"
echo "=========================================="
echo ""
echo "1. Test locally:"
echo "   cd examples/production-deployment"
echo "   docker-compose up -d"
echo ""
echo "2. Push multi-arch to Docker Hub:"
echo "   docker login"
echo "   ./build-production-images.sh $VERSION $REGISTRY true"
echo ""
