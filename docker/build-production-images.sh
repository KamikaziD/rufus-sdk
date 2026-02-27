#!/bin/bash
# Build and optionally push production Rufus images
# These images install rufus-sdk from PyPI instead of copying source

set -e

# Configuration
VERSION="${1:-0.6.0}"
REGISTRY="${2:-yourname}"  # Change to your Docker Hub username
PUSH="${3:-false}"

echo "=========================================="
echo "  Building Rufus Production Images"
echo "=========================================="
echo "Version: $VERSION"
echo "Registry: $REGISTRY"
echo "Push to Docker Hub: $PUSH"
echo ""

# Build images
echo "🔨 Building rufus-server..."
docker build -f Dockerfile.rufus-server-prod \
    -t ${REGISTRY}/rufus-server:${VERSION} \
    -t ${REGISTRY}/rufus-server:latest \
    ..

echo "🔨 Building rufus-worker..."
docker build -f Dockerfile.rufus-worker-prod \
    -t ${REGISTRY}/rufus-worker:${VERSION} \
    -t ${REGISTRY}/rufus-worker:latest \
    ..

echo "🔨 Building rufus-flower..."
docker build -f Dockerfile.rufus-flower-prod \
    -t ${REGISTRY}/rufus-flower:${VERSION} \
    -t ${REGISTRY}/rufus-flower:latest \
    ..

echo ""
echo "✅ Build complete!"
echo ""
echo "Images created:"
echo "  - ${REGISTRY}/rufus-server:${VERSION}"
echo "  - ${REGISTRY}/rufus-server:latest"
echo "  - ${REGISTRY}/rufus-worker:${VERSION}"
echo "  - ${REGISTRY}/rufus-worker:latest"
echo "  - ${REGISTRY}/rufus-flower:${VERSION}"
echo "  - ${REGISTRY}/rufus-flower:latest"
echo ""

# Push if requested
if [ "$PUSH" = "true" ]; then
    echo "📤 Pushing to Docker Hub..."
    echo ""

    docker push ${REGISTRY}/rufus-server:${VERSION}
    docker push ${REGISTRY}/rufus-server:latest

    docker push ${REGISTRY}/rufus-worker:${VERSION}
    docker push ${REGISTRY}/rufus-worker:latest

    docker push ${REGISTRY}/rufus-flower:${VERSION}
    docker push ${REGISTRY}/rufus-flower:latest

    echo ""
    echo "✅ Push complete!"
    echo ""
    echo "Users can now pull with:"
    echo "  docker pull ${REGISTRY}/rufus-server:latest"
    echo "  docker pull ${REGISTRY}/rufus-worker:latest"
    echo "  docker pull ${REGISTRY}/rufus-flower:latest"
else
    echo "To push to Docker Hub, run:"
    echo "  ./build-production-images.sh $VERSION $REGISTRY true"
    echo ""
    echo "Or push manually:"
    echo "  docker push ${REGISTRY}/rufus-server:${VERSION}"
    echo "  docker push ${REGISTRY}/rufus-worker:${VERSION}"
    echo "  docker push ${REGISTRY}/rufus-flower:${VERSION}"
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
echo "2. Push to Docker Hub:"
echo "   docker login"
echo "   ./build-production-images.sh $VERSION $REGISTRY true"
echo ""
