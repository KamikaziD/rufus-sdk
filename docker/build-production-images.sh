#!/bin/bash
# Build and push production Rufus images for linux/amd64 + linux/arm64
# These images install rufus-sdk from PyPI instead of copying source
#
# Usage:
#   ./build-production-images.sh [VERSION] [REGISTRY] [PUSH=true|false]
#   ./build-production-images.sh 0.6.3 ruhfuskdev true

set -e

# Configuration
VERSION="${1:-0.7.5}"
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
if ! docker buildx inspect rufus-builder &>/dev/null; then
    echo "Creating multi-platform buildx builder..."
    docker buildx create --name rufus-builder --driver docker-container --bootstrap --use
else
    docker buildx use rufus-builder
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

echo "Building rufus-server..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.rufus-server-prod \
    -t ${REGISTRY}/rufus-server:${VERSION} \
    -t ${REGISTRY}/rufus-server:latest \
    ..

echo "Building rufus-worker..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.rufus-worker-prod \
    -t ${REGISTRY}/rufus-worker:${VERSION} \
    -t ${REGISTRY}/rufus-worker:latest \
    ..

echo "Building rufus-flower..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.rufus-flower-prod \
    -t ${REGISTRY}/rufus-flower:${VERSION} \
    -t ${REGISTRY}/rufus-flower:latest \
    ..

echo "Building rufus-dashboard..."
docker buildx build ${BUILD_PLATFORMS} ${BUILD_OUTPUT} \
    -f Dockerfile.rufus-dashboard-prod \
    -t ${REGISTRY}/rufus-dashboard:${VERSION} \
    -t ${REGISTRY}/rufus-dashboard:latest \
    ..

echo ""
echo "Build complete!"
echo ""

if [ "$PUSH" = "true" ]; then
    echo "Images pushed to Docker Hub:"
    echo "  - ${REGISTRY}/rufus-server:${VERSION}"
    echo "  - ${REGISTRY}/rufus-server:latest"
    echo "  - ${REGISTRY}/rufus-worker:${VERSION}"
    echo "  - ${REGISTRY}/rufus-worker:latest"
    echo "  - ${REGISTRY}/rufus-flower:${VERSION}"
    echo "  - ${REGISTRY}/rufus-flower:latest"
    echo "  - ${REGISTRY}/rufus-dashboard:${VERSION}"
    echo "  - ${REGISTRY}/rufus-dashboard:latest"
    echo ""
    echo "Verify multi-arch manifests:"
    echo "  docker buildx imagetools inspect ${REGISTRY}/rufus-server:${VERSION}"
else
    echo "Images loaded locally (linux/amd64 only):"
    echo "  - ${REGISTRY}/rufus-server:${VERSION}"
    echo "  - ${REGISTRY}/rufus-worker:${VERSION}"
    echo "  - ${REGISTRY}/rufus-flower:${VERSION}"
    echo "  - ${REGISTRY}/rufus-dashboard:${VERSION}"
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
