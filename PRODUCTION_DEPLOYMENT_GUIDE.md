# Production Deployment Guide - Docker-Based Workflow Updates

**Zero-Downtime Workflow Updates with Kubernetes**

---

## **Quick Start**

### **1. Update a Workflow**

```bash
# Edit step function
vim my_app/steps.py

# Add new function
def check_velocity(state: PaymentState, context: StepContext) -> dict:
    """Check transaction velocity."""
    recent = query_recent_transactions(state.user_id, minutes=5)
    if len(recent) > 5:
        raise ValueError("Velocity exceeded")
    return {"velocity_check": "passed"}

# Update workflow YAML
vim workflows/payment_processing.yaml
```

```yaml
workflow_version: "1.1.0"  # Bump version

steps:
  # Add new step
  - name: "Check_Velocity"
    type: "STANDARD"
    function: "my_app.steps.check_velocity"
    automate_next: true
```

### **2. Commit and Push**

```bash
git add my_app/steps.py workflows/payment_processing.yaml
git commit -m "feat: Add velocity check (v1.1.0)"
git push origin main
```

### **3. Automatic Deployment**

```
✅ CI/CD pipeline triggers automatically:
   • Build Docker image
   • Run smoke tests
   • Push to registry
   • Deploy to staging (if develop branch)
   • Deploy to production (if main branch)

⏱️  Total time: ~15 minutes
🎯 Zero downtime
🔄 Automatic rollback on failure
```

---

## **Architecture**

### **Immutable Infrastructure**

```
WORKFLOWS + CODE → Docker Image → Kubernetes Deployment
```

**Key principle:** Workflows and step functions are **baked into** Docker images.
- ✅ No hot-reload
- ✅ No module import issues
- ✅ No memory leaks
- ✅ Atomic updates

### **Deployment Flow**

```
Developer
  ↓ git push
GitHub Actions
  ↓ builds image
Container Registry
  ↓ webhook
Control Plane
  ↓ triggers
Kubernetes
  ↓ rolling update
Workers (v1.0.0 → v1.1.0)
```

---

## **Files Overview**

| File | Purpose |
|------|---------|
| `docker/Dockerfile.rufus-worker-production` | Production Dockerfile with embedded workflows |
| `docker/entrypoint-worker-production.sh` | Worker entrypoint with health checks |
| `k8s/worker-deployment.yaml` | Kubernetes deployment manifest |
| `.github/workflows/deploy-worker.yml` | CI/CD pipeline |
| `docs/DOCKER_WORKFLOW_UPDATES.md` | Complete architecture documentation |

---

## **Deployment Strategies**

### **1. Rolling Update (Default)**

```yaml
# k8s/worker-deployment.yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 1
```

**Flow:**
```
5 pods (v1.0.0)
  ↓ Update 1 pod
4 pods (v1.0.0) + 1 pod (v1.1.0)
  ↓ Update 1 pod
3 pods (v1.0.0) + 2 pods (v1.1.0)
  ↓ ...
5 pods (v1.1.0)
```

**Time:** ~5-10 minutes

### **2. Canary Deployment**

```json
// API request to control plane
{
  "rollout_strategy": "canary",
  "canary_percentage": 20,
  "health_check_delay": 300
}
```

**Flow:**
```
T+0:   Deploy to 20% of workers
T+5min: Monitor error rates, health checks
T+6min: If healthy → promote to 100%
        If unhealthy → rollback
```

**Time:** ~15 minutes (with health monitoring)

### **3. Blue-Green Deployment**

```bash
# Deploy to "green" environment
kubectl apply -f k8s/worker-deployment-green.yaml

# Switch traffic
kubectl patch service rufus-worker \
  -p '{"spec":{"selector":{"deployment":"green"}}}'

# Cleanup "blue"
kubectl delete deployment rufus-worker-blue
```

---

## **Rollback**

### **Automatic Rollback**

If canary deployment fails health checks:
- ✅ Control plane automatically rolls back
- ✅ Original version restored
- ✅ Alert sent to Slack/PagerDuty

### **Manual Rollback**

```bash
# Via kubectl
kubectl rollout undo deployment/rufus-worker

# Via control plane API
curl -X POST $CONTROL_PLANE_URL/api/v1/deployments/{id}/rollback
```

---

## **Monitoring**

### **Deployment Status**

```bash
# Watch deployment progress
kubectl rollout status deployment/rufus-worker

# Get deployment history
kubectl rollout history deployment/rufus-worker

# Check pod versions
kubectl get pods -l app=rufus-worker -o jsonpath='{.items[*].metadata.labels.version}'
```

### **Health Checks**

**Liveness probe:** `/health`
- Checks if worker is alive
- Restart pod if failing

**Readiness probe:** `/ready`
- Checks if worker is ready to accept tasks
- Remove from load balancer if failing

### **Metrics**

```bash
# Worker version distribution
curl $CONTROL_PLANE_URL/api/v1/deployments/current

# Response:
{
  "total_workers": 5,
  "versions": {
    "1.1.0": 5
  },
  "rollout_status": "stable"
}
```

---

## **CI/CD Pipeline**

### **Stages**

1. **Build** - Build Docker image
2. **Test** - Run smoke tests
3. **Scan** - Security scan with Trivy
4. **Deploy Staging** - Auto-deploy to staging (develop branch)
5. **Integration Tests** - Run tests against staging
6. **Deploy Production** - Auto-deploy to prod (main branch, requires approval)

### **Triggers**

- **On push to main:** Production deployment
- **On push to develop:** Staging deployment
- **Manual:** Via workflow_dispatch

### **Environment Variables**

```bash
# GitHub Secrets required:
REGISTRY_USERNAME
REGISTRY_PASSWORD
CONTROL_PLANE_URL_STAGING
CONTROL_PLANE_URL_PRODUCTION
DEPLOY_TOKEN_STAGING
DEPLOY_TOKEN_PRODUCTION
SLACK_WEBHOOK_URL
```

---

## **Local Development**

### **Build Image Locally**

```bash
# Build production image
docker build \
  -f docker/Dockerfile.rufus-worker-production \
  -t rufus-worker:local \
  --build-arg WORKFLOW_VERSION=1.0.0-dev \
  --build-arg BUILD_SHA=$(git rev-parse HEAD) \
  --build-arg BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ") \
  .

# Run locally
docker run -it --rm \
  -e CELERY_BROKER_URL=redis://localhost:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://localhost:6379/0 \
  rufus-worker:local
```

### **Test Workflow Changes**

```bash
# 1. Make changes to workflows/my_app

# 2. Rebuild image
docker build -t rufus-worker:local .

# 3. Run smoke tests
docker run --rm rufus-worker:local \
  python -c "from my_app.steps import *; print('✅ OK')"

# 4. Start worker
docker compose -f docker-compose.dev.yml up worker
```

---

## **Production Checklist**

### **Before Deployment**

- [ ] Workflow version bumped
- [ ] Step functions tested locally
- [ ] Smoke tests pass
- [ ] Security scan clean (no CRITICAL vulnerabilities)
- [ ] Database migrations applied (if schema changed)
- [ ] Rollback plan documented

### **During Deployment**

- [ ] Monitor canary health (5-10 min)
- [ ] Check error rates in Grafana/Datadog
- [ ] Watch worker logs for exceptions
- [ ] Verify new workflows executing correctly

### **After Deployment**

- [ ] Confirm all workers updated (`kubectl get pods`)
- [ ] Run integration tests
- [ ] Update deployment docs
- [ ] Notify team in Slack

---

## **Troubleshooting**

### **Deployment stuck**

```bash
# Check pod status
kubectl describe pod rufus-worker-xxx

# Check events
kubectl get events --sort-by='.lastTimestamp'

# Check image pull
kubectl get pods -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'
```

### **Workers not starting**

```bash
# Check logs
kubectl logs rufus-worker-xxx

# Common issues:
# - Missing secret (RUFUS_API_KEY)
# - Image pull error (check registry auth)
# - Health check failing (check /health endpoint)
```

### **Canary failing health checks**

```bash
# Get canary deployment status
curl $CONTROL_PLANE_URL/api/v1/deployments/{id}

# Check error rates
kubectl logs -l deployment=canary --tail=100 | grep ERROR

# Manual rollback
curl -X POST $CONTROL_PLANE_URL/api/v1/deployments/{id}/rollback
```

---

## **Comparison: Git Reload vs Docker**

| | Git Hot Reload | Docker Update |
|-|----------------|---------------|
| **Update Time** | <60s | 5-15min |
| **Pitfalls** | Many (see docs) | None |
| **Rollback** | Manual | Automatic |
| **Testing** | Limited | Full CI/CD |
| **Production Ready** | ❌ No | ✅ Yes |

**Recommendation:** Use Docker-based updates for production.

---

## **Next Steps**

1. **Setup CI/CD:**
   - Configure GitHub secrets
   - Test pipeline in staging
   - Enable Slack notifications

2. **Setup Monitoring:**
   - Deploy Prometheus/Grafana
   - Configure alerts
   - Create dashboards

3. **Harden Security:**
   - Enable image signing
   - Setup vulnerability scanning
   - Implement RBAC

4. **Document Runbooks:**
   - Deployment procedures
   - Rollback procedures
   - Incident response

---

**Ready for production!** 🚀
