# Production-Grade Docker Workflow Updates

**Architecture:** Immutable container updates with zero-downtime rollouts

---

## **Architecture Overview**

```
┌─────────────────────────────────────────────────────────┐
│                    CI/CD Pipeline                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Git Push  │→ │Build     │→ │Registry  │             │
│  │(workflow)│  │(Docker)  │  │(Harbor)  │             │
│  └──────────┘  └──────────┘  └──────────┘             │
└────────────────────┬────────────────────────────────────┘
                     │ Webhook
                     ▼
┌─────────────────────────────────────────────────────────┐
│              CONTROL PLANE                               │
│  ┌────────────────────────────────────────────────┐    │
│  │  Workflow Update Controller                     │    │
│  │  • Validates new image                          │    │
│  │  • Creates deployment spec                      │    │
│  │  • Triggers rollout (canary → full)            │    │
│  │  • Monitors health                              │    │
│  └────────────────┬───────────────────────────────┘    │
└────────────────────┼────────────────────────────────────┘
                     │ K8s API
                     ▼
┌─────────────────────────────────────────────────────────┐
│              KUBERNETES CLUSTER                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Rolling Update (5 workers)                       │  │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐        │  │
│  │  │ v1  │ │ v1  │ │ v1  │ │ v1  │ │ v1  │  ← Old  │  │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘        │  │
│  │     ↓                                             │  │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐        │  │
│  │  │ v2  │ │ v1  │ │ v1  │ │ v1  │ │ v1  │  ← 20%  │  │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘        │  │
│  │     ↓       ↓       ↓       ↓       ↓            │  │
│  │  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐        │  │
│  │  │ v2  │ │ v2  │ │ v2  │ │ v2  │ │ v2  │  ← 100% │  │
│  │  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘        │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## **1. Docker Image Structure**

### **Dockerfile for Worker**

```dockerfile
# docker/Dockerfile.rufus-worker-workflows
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages

# Create app user
RUN useradd -m -u 1000 rufus && \
    mkdir -p /app /var/lib/rufus && \
    chown -R rufus:rufus /app /var/lib/rufus

USER rufus
WORKDIR /app

# Copy Rufus SDK
COPY --chown=rufus:rufus src/rufus /app/src/rufus
COPY --chown=rufus:rufus src/rufus_edge /app/src/rufus_edge

# Copy workflow definitions and step functions
# THIS IS THE KEY: Workflows baked into image
COPY --chown=rufus:rufus workflows/ /app/workflows/
COPY --chown=rufus:rufus my_app/ /app/my_app/

# Environment
ENV PYTHONPATH=/app
ENV WORKFLOWS_DIR=/app/workflows

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health').raise_for_status()"

# Entrypoint
COPY --chown=rufus:rufus docker/entrypoint-worker.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["celery", "-A", "examples.celery_edge_worker.rufus_worker_edge", "worker", "--loglevel=info"]
```

### **Project Structure in Image**

```
/app/
├── src/
│   ├── rufus/          # Rufus SDK
│   └── rufus_edge/     # Edge agent
├── workflows/          # Workflow YAML definitions
│   ├── payment_processing.yaml
│   ├── fraud_detection.yaml
│   └── order_fulfillment.yaml
├── my_app/             # Step functions
│   ├── __init__.py
│   ├── steps.py        # All step functions
│   ├── models.py       # State models
│   └── validators.py   # Validation logic
└── examples/
    └── celery_edge_worker/
        └── rufus_worker_edge.py
```

**Key insight:** Workflows + step functions are **immutable** in the image. No hot reload needed!

---

## **2. CI/CD Pipeline**

### **GitHub Actions Workflow**

```yaml
# .github/workflows/build-worker.yml
name: Build and Deploy Worker

on:
  push:
    paths:
      - 'workflows/**'
      - 'my_app/**'
      - 'docker/Dockerfile.rufus-worker-workflows'

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      image_tag: ${{ steps.meta.outputs.tags }}

    steps:
      - uses: actions/checkout@v4

      - name: Extract version from workflow
        id: version
        run: |
          # Extract version from main workflow file
          VERSION=$(yq '.workflow_version' workflows/payment_processing.yaml)
          echo "version=$VERSION" >> $GITHUB_OUTPUT

          # Generate image tag
          TAG="v${VERSION}-${GITHUB_SHA::8}"
          echo "tag=$TAG" >> $GITHUB_OUTPUT

      - name: Docker meta
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: myregistry.io/rufus-worker
          tags: |
            type=raw,value=${{ steps.version.outputs.tag }}
            type=raw,value=latest

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: docker/Dockerfile.rufus-worker-workflows
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: |
            org.opencontainers.image.version=${{ steps.version.outputs.version }}
            workflow.version=${{ steps.version.outputs.version }}
            workflow.commit=${{ github.sha }}

      - name: Run smoke tests
        run: |
          # Test new image
          docker run --rm ${{ steps.meta.outputs.tags }} \
            python -c "
              from my_app.steps import validate_payment, check_fraud
              from my_app.models import PaymentState
              print('✅ All functions importable')
            "

      - name: Trigger deployment
        run: |
          curl -X POST ${{ secrets.CONTROL_PLANE_URL }}/api/v1/deployments \
            -H "Authorization: Bearer ${{ secrets.DEPLOY_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d '{
              "image": "${{ steps.meta.outputs.tags }}",
              "version": "${{ steps.version.outputs.version }}",
              "commit_sha": "${{ github.sha }}",
              "rollout_strategy": "canary"
            }'
```

---

## **3. Control Plane Deployment API**

```python
# src/rufus_server/deployments.py

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from kubernetes import client, config
from datetime import datetime
import logging

router = APIRouter(prefix="/api/v1/deployments")
logger = logging.getLogger(__name__)


class DeploymentRequest(BaseModel):
    image: str  # e.g., "myregistry.io/rufus-worker:v1.2.0-abc123"
    version: str  # e.g., "1.2.0"
    commit_sha: str
    rollout_strategy: str = "canary"  # canary, rolling, blue-green
    canary_percentage: int = 20
    health_check_delay: int = 300  # 5 minutes


class DeploymentStatus(BaseModel):
    deployment_id: str
    status: str  # pending, canary, rolling, completed, failed
    image: str
    version: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    rollout_progress: dict


@router.post("/")
async def create_deployment(
    request: DeploymentRequest,
    background_tasks: BackgroundTasks,
    db: Database = Depends(get_db)
):
    """
    Trigger workflow update deployment.

    Process:
    1. Validate image exists and is accessible
    2. Create deployment record
    3. Trigger canary deployment (background)
    4. Monitor health
    5. Roll out to all workers
    """

    # 1. Validate image
    if not await _validate_image(request.image):
        raise HTTPException(status_code=400, detail="Image not found or inaccessible")

    # 2. Create deployment record
    deployment_id = str(uuid.uuid4())

    await db.execute("""
        INSERT INTO workflow_deployments
        (deployment_id, image, version, commit_sha, status, rollout_strategy, created_at)
        VALUES ($1, $2, $3, $4, 'pending', $5, NOW())
    """, deployment_id, request.image, request.version, request.commit_sha, request.rollout_strategy)

    # 3. Trigger deployment in background
    background_tasks.add_task(
        _execute_deployment,
        deployment_id=deployment_id,
        request=request
    )

    logger.info(f"[Deployment] Created {deployment_id} for version {request.version}")

    return {
        "deployment_id": deployment_id,
        "status": "pending",
        "image": request.image,
        "version": request.version
    }


async def _execute_deployment(deployment_id: str, request: DeploymentRequest):
    """
    Execute deployment with canary rollout.

    Steps:
    1. Canary: Deploy to 20% of workers
    2. Monitor: Watch for errors (5 minutes)
    3. Promote: Roll out to 100% if healthy
    4. Rollback: Revert if errors detected
    """

    try:
        # Load K8s config
        config.load_incluster_config()  # Running in cluster
        apps_v1 = client.AppsV1Api()

        deployment_name = "rufus-worker"
        namespace = "default"

        # Get current deployment
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )

        current_image = deployment.spec.template.spec.containers[0].image
        logger.info(f"[Deployment] Current image: {current_image}")

        # STEP 1: Canary deployment (20%)
        await _update_deployment_status(deployment_id, "canary")

        canary_replicas = int(deployment.spec.replicas * request.canary_percentage / 100)
        logger.info(f"[Deployment] Starting canary with {canary_replicas} replicas")

        # Create canary deployment
        canary_deployment = _create_canary_deployment(
            base_deployment=deployment,
            image=request.image,
            replicas=canary_replicas
        )

        apps_v1.create_namespaced_deployment(
            namespace=namespace,
            body=canary_deployment
        )

        # STEP 2: Monitor canary health
        logger.info(f"[Deployment] Monitoring canary for {request.health_check_delay}s")
        await asyncio.sleep(request.health_check_delay)

        canary_healthy = await _check_canary_health(
            deployment_id=deployment_id,
            canary_deployment_name=f"{deployment_name}-canary"
        )

        if not canary_healthy:
            # Rollback canary
            logger.error(f"[Deployment] Canary unhealthy, rolling back")
            await _rollback_deployment(deployment_id, canary_deployment, apps_v1)
            return

        # STEP 3: Promote to full rollout
        await _update_deployment_status(deployment_id, "rolling")
        logger.info(f"[Deployment] Canary healthy, promoting to full rollout")

        # Update main deployment with new image
        deployment.spec.template.spec.containers[0].image = request.image
        deployment.spec.template.metadata.labels["version"] = request.version

        apps_v1.patch_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=deployment
        )

        # STEP 4: Wait for rolling update
        await _wait_for_rollout(apps_v1, deployment_name, namespace)

        # STEP 5: Cleanup canary
        apps_v1.delete_namespaced_deployment(
            name=f"{deployment_name}-canary",
            namespace=namespace
        )

        # Success!
        await _update_deployment_status(deployment_id, "completed")
        logger.info(f"[Deployment] {deployment_id} completed successfully")

    except Exception as e:
        logger.error(f"[Deployment] {deployment_id} failed: {e}", exc_info=True)
        await _update_deployment_status(deployment_id, "failed", error=str(e))

        # Attempt rollback
        try:
            await _rollback_deployment(deployment_id, current_image, apps_v1)
        except Exception as rollback_error:
            logger.error(f"[Deployment] Rollback failed: {rollback_error}")


def _create_canary_deployment(base_deployment, image: str, replicas: int):
    """Create canary deployment with new image."""
    canary = client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=f"{base_deployment.metadata.name}-canary",
            labels=base_deployment.metadata.labels.copy()
        ),
        spec=client.V1DeploymentSpec(
            replicas=replicas,
            selector=base_deployment.spec.selector,
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(
                    labels={
                        **base_deployment.spec.template.metadata.labels,
                        "deployment": "canary"
                    }
                ),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name=base_deployment.spec.template.spec.containers[0].name,
                            image=image,  # New image
                            env=base_deployment.spec.template.spec.containers[0].env,
                            resources=base_deployment.spec.template.spec.containers[0].resources,
                        )
                    ]
                )
            )
        )
    )

    return canary


async def _check_canary_health(deployment_id: str, canary_deployment_name: str) -> bool:
    """
    Check canary deployment health.

    Criteria:
    - All pods running
    - No crash loops
    - Health checks passing
    - No increase in error rate
    """

    # Query metrics from database
    error_rate = await db.fetchval("""
        SELECT COUNT(*)
        FROM workflow_executions
        WHERE status = 'FAILED'
          AND worker_deployment = $1
          AND created_at > NOW() - INTERVAL '5 minutes'
    """, canary_deployment_name)

    # Check K8s pod status
    core_v1 = client.CoreV1Api()
    pods = core_v1.list_namespaced_pod(
        namespace="default",
        label_selector=f"deployment=canary"
    )

    all_ready = all(
        pod.status.phase == "Running" and
        all(condition.status == "True" for condition in pod.status.conditions if condition.type == "Ready")
        for pod in pods.items
    )

    healthy = all_ready and error_rate < 5  # Max 5 errors in 5 minutes

    logger.info(f"[Canary] Health check: pods_ready={all_ready}, errors={error_rate}, healthy={healthy}")

    return healthy


async def _wait_for_rollout(apps_v1, deployment_name: str, namespace: str, timeout: int = 600):
    """Wait for rolling update to complete."""
    start = time.time()

    while time.time() - start < timeout:
        deployment = apps_v1.read_namespaced_deployment(
            name=deployment_name,
            namespace=namespace
        )

        # Check if rollout complete
        if (deployment.status.updated_replicas == deployment.spec.replicas and
            deployment.status.available_replicas == deployment.spec.replicas):
            logger.info(f"[Rollout] Completed for {deployment_name}")
            return

        logger.info(
            f"[Rollout] Progress: {deployment.status.updated_replicas}/{deployment.spec.replicas} updated, "
            f"{deployment.status.available_replicas}/{deployment.spec.replicas} available"
        )

        await asyncio.sleep(10)

    raise TimeoutError(f"Rollout timed out after {timeout}s")


async def _rollback_deployment(deployment_id: str, previous_image: str, apps_v1):
    """Rollback to previous image."""
    logger.warning(f"[Deployment] Rolling back {deployment_id}")

    # Use kubectl rollout undo
    subprocess.run([
        "kubectl", "rollout", "undo",
        "deployment/rufus-worker",
        "-n", "default"
    ], check=True)

    await _update_deployment_status(deployment_id, "rolled_back")


@router.get("/{deployment_id}")
async def get_deployment_status(deployment_id: str, db: Database = Depends(get_db)):
    """Get deployment status."""
    deployment = await db.fetchrow("""
        SELECT * FROM workflow_deployments WHERE deployment_id = $1
    """, deployment_id)

    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    return DeploymentStatus(**deployment)


@router.post("/{deployment_id}/rollback")
async def rollback_deployment(deployment_id: str):
    """Manually trigger rollback."""
    # Similar to _rollback_deployment but as API endpoint
    pass
```

---

## **4. Kubernetes Deployment Manifest**

```yaml
# k8s/worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rufus-worker
  namespace: default
  labels:
    app: rufus-worker
    component: celery
spec:
  replicas: 5

  # Rolling update strategy
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # Max 1 extra pod during update
      maxUnavailable: 1  # Max 1 pod down during update

  selector:
    matchLabels:
      app: rufus-worker

  template:
    metadata:
      labels:
        app: rufus-worker
        version: "1.0.0"  # Updated by control plane
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"

    spec:
      # Graceful shutdown
      terminationGracePeriodSeconds: 300  # 5 minutes to drain tasks

      containers:
      - name: worker
        image: myregistry.io/rufus-worker:v1.0.0  # Updated by control plane
        imagePullPolicy: Always

        env:
        - name: CELERY_BROKER_URL
          value: "redis://redis:6379/0"
        - name: CELERY_RESULT_BACKEND
          value: "redis://redis:6379/0"
        - name: RUFUS_CONTROL_PLANE_URL
          value: "http://control-plane:8000"
        - name: WORKFLOWS_DIR
          value: "/app/workflows"
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name

        # Resource limits
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"

        # Health checks
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2

        # Lifecycle hooks
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15 && celery -A rufus_worker_edge control shutdown"]

        # Volume mounts
        volumeMounts:
        - name: worker-data
          mountPath: /var/lib/rufus

      volumes:
      - name: worker-data
        emptyDir: {}  # Ephemeral storage (OK for edge agent SQLite)
```

---

## **5. Complete Update Flow**

### **Developer Workflow**

```bash
# 1. Developer adds new step function
cat > my_app/steps.py <<EOF
def check_velocity(state: PaymentState, context: StepContext) -> dict:
    """Check transaction velocity."""
    recent_txns = query_recent_transactions(state.user_id, minutes=5)
    if len(recent_txns) > 5:
        raise ValueError("Velocity limit exceeded")
    return {"velocity_check": "passed"}
EOF

# 2. Update workflow YAML
yq -i '.workflow_version = "1.1.0"' workflows/payment_processing.yaml
yq -i '.steps += [{"name": "Check_Velocity", "function": "my_app.steps.check_velocity"}]' workflows/payment_processing.yaml

# 3. Commit and push
git add my_app/steps.py workflows/payment_processing.yaml
git commit -m "feat: Add velocity check step (v1.1.0)"
git push origin main

# 4. CI/CD pipeline auto-triggers:
#    - Build Docker image: myregistry.io/rufus-worker:v1.1.0-abc123
#    - Run smoke tests
#    - Push to registry
#    - Trigger deployment via API

# 5. Control plane executes canary rollout:
#    T+0:   20% workers updated (1 pod)
#    T+5min: Monitor canary health
#    T+6min: Promote to 100% (rolling update)
#    T+15min: All workers updated

# Total time: ~15 minutes
# Zero downtime ✅
# Zero module reload issues ✅
# Automatic rollback on failure ✅
```

---

## **6. Monitoring and Observability**

### **Deployment Dashboard**

```python
# src/rufus_server/dashboards.py

@router.get("/deployments/current")
async def get_current_deployment():
    """Get currently deployed version across worker fleet."""

    # Query K8s for running pods
    core_v1 = client.CoreV1Api()
    pods = core_v1.list_namespaced_pod(
        namespace="default",
        label_selector="app=rufus-worker"
    )

    # Count versions
    version_counts = {}
    for pod in pods.items:
        version = pod.metadata.labels.get("version", "unknown")
        version_counts[version] = version_counts.get(version, 0) + 1

    return {
        "total_workers": len(pods.items),
        "versions": version_counts,
        "rollout_status": "stable" if len(version_counts) == 1 else "updating"
    }
```

### **Metrics**

```python
from prometheus_client import Counter, Histogram, Gauge

deployment_started = Counter(
    "workflow_deployment_started_total",
    "Total deployments started",
    ["version"]
)

deployment_completed = Counter(
    "workflow_deployment_completed_total",
    "Total deployments completed",
    ["version", "status"]
)

deployment_duration = Histogram(
    "workflow_deployment_duration_seconds",
    "Deployment duration",
    ["version"]
)

active_workflow_version = Gauge(
    "active_workflow_version_info",
    "Active workflow versions",
    ["version", "worker_id"]
)
```

---

## **7. Comparison: Git Reload vs Docker Update**

| Aspect | Git Hot Reload | Docker Update |
|--------|---------------|---------------|
| **Update Time** | <60s | 5-15min |
| **Downtime** | None | None |
| **Module Reload** | ❌ Issues | ✅ Fresh interpreter |
| **Version Conflicts** | ❌ Possible | ✅ Impossible |
| **Memory Leaks** | ❌ Yes | ✅ No |
| **Rollback** | 🟡 Git revert | ✅ K8s rollout undo |
| **Testing** | 🟡 Smoke tests only | ✅ Full CI/CD |
| **Atomicity** | ❌ Partial updates | ✅ All-or-nothing |
| **Debugging** | 🟡 Hard | ✅ Easy (image SHA) |
| **Audit Trail** | ✅ Git log | ✅ Container registry |
| **Production Ready** | ❌ No | ✅ Yes |

---

## **8. Best Practices**

### **✅ DO**

1. **Version everything:**
   ```yaml
   # Workflow YAML
   workflow_version: "1.2.0"

   # Docker image
   myregistry.io/rufus-worker:v1.2.0-abc123

   # K8s label
   version: "1.2.0"
   ```

2. **Test before deploy:**
   ```bash
   # Smoke tests in CI
   docker run --rm $IMAGE python -c "from my_app.steps import *"

   # Integration tests
   docker-compose -f docker-compose.test.yml up --abort-on-container-exit
   ```

3. **Gradual rollouts:**
   ```
   Canary (20%) → Monitor (5 min) → Full rollout
   ```

4. **Monitor health:**
   ```python
   # Track error rates per version
   SELECT version, COUNT(*) as errors
   FROM workflow_executions
   WHERE status = 'FAILED'
   GROUP BY version
   ```

### **❌ DON'T**

1. **Don't skip canary:** Always test on subset first
2. **Don't rush:** Wait for health checks
3. **Don't deploy at peak:** Schedule during low traffic
4. **Don't ignore metrics:** Watch error rates

---

## **Recommendation**

**Use Docker-based updates for production:**
- ✅ Safe (no module reload)
- ✅ Testable (full CI/CD)
- ✅ Rollback-able (K8s native)
- ✅ Observable (image SHA tracking)

**Trade-off:** 15 min updates vs 60s (acceptable for production)

Ready to implement this? 🚀
