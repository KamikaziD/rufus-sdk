# Advanced & Enterprise Features

Complete guide to Tier 4 (Advanced) and Tier 5 (Enterprise) features for Ruvon Edge.

## Overview

This document covers 6 advanced capabilities that extend the Ruvon Edge command system for enterprise deployments:

**Tier 4 - Advanced Features** (Production-Ready):
1. **Command Versioning** - Track command definition changes over time
2. **Webhook Notifications** - Real-time event notifications for integrations
3. **Command Rate Limiting** - Protect against command flooding and abuse

**Tier 5 - Enterprise Extensions** (Architecture & Patterns):
4. **GraphQL API** - Powerful querying alternative to REST
5. **Multi-Cloud Deployment** - Deploy across AWS/Azure/GCP
6. **AI Anomaly Detection** - ML-based fraud and anomaly detection

---

# Tier 4: Advanced Features

## 1. Command Versioning

Track command definition changes over time with full schema evolution support.

### Database Schema

```sql
CREATE TABLE command_versions (
    command_type VARCHAR(100) NOT NULL,
    version VARCHAR(50) NOT NULL,
    schema_definition JSONB NOT NULL,
    changelog TEXT,
    is_active BOOLEAN DEFAULT true,
    is_deprecated BOOLEAN DEFAULT false,
    deprecated_reason TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(command_type, version)
);

CREATE TABLE command_changelog (
    command_type VARCHAR(100) NOT NULL,
    from_version VARCHAR(50),
    to_version VARCHAR(50) NOT NULL,
    change_type VARCHAR(50) NOT NULL,  -- breaking, enhancement, bugfix
    changes JSONB NOT NULL,
    migration_guide TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Link commands to versions
ALTER TABLE device_commands
ADD COLUMN command_version VARCHAR(50);
```

### Use Cases

**1. Schema Evolution**:
```sql
-- v1.0.0: Basic restart
INSERT INTO command_versions (command_type, version, schema_definition, changelog) VALUES
    ('restart', '1.0.0',
     '{"type":"object","properties":{"delay_seconds":{"type":"integer"}},"required":[]}',
     'Initial version');

-- v2.0.0: Add graceful shutdown
INSERT INTO command_versions (command_type, version, schema_definition, changelog) VALUES
    ('restart', '2.0.0',
     '{"type":"object","properties":{"delay_seconds":{"type":"integer"},"graceful":{"type":"boolean","default":true}},"required":[]}',
     'Added graceful shutdown option');

-- Track the change
INSERT INTO command_changelog (command_type, from_version, to_version, change_type, changes) VALUES
    ('restart', '1.0.0', '2.0.0', 'enhancement',
     '{"added":["graceful"],"changed":[],"removed":[]}');
```

**2. Deprecation Workflow**:
```sql
-- Mark old version as deprecated
UPDATE command_versions
SET is_deprecated = true,
    deprecated_reason = 'Use v2.0.0 with graceful shutdown'
WHERE command_type = 'restart' AND version = '1.0.0';
```

**3. Version Analytics**:
```sql
-- Which versions are still in use?
SELECT command_type, command_version, COUNT(*) as usage_count
FROM device_commands
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY command_type, command_version
ORDER BY usage_count DESC;
```

### API Endpoints

```python
# Get command versions
GET /api/v1/commands/{command_type}/versions

# Get specific version
GET /api/v1/commands/{command_type}/versions/{version}

# Get changelog between versions
GET /api/v1/commands/{command_type}/changelog?from=1.0.0&to=2.0.0
```

### Best Practices

1. **Semantic Versioning**: Use MAJOR.MINOR.PATCH format
   - MAJOR: Breaking changes
   - MINOR: New features (backward compatible)
   - PATCH: Bug fixes

2. **Deprecation Policy**:
   - Announce deprecation 6 months before removal
   - Provide migration guide
   - Keep deprecated versions functional

3. **Version in Audit Log**:
```python
audit_event = AuditEvent(
    event_type=EventType.COMMAND_CREATED,
    command_type="restart",
    command_data={"version": "2.0.0", ...}  # Track version used
)
```

---

## 2. Webhook Notifications

Real-time event notifications for external integrations (Slack, PagerDuty, custom systems).

### Database Schema

```sql
CREATE TABLE webhook_registrations (
    webhook_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    url TEXT NOT NULL,
    events JSONB NOT NULL,  -- ["command_completed", "approval_pending"]
    secret VARCHAR(100),  -- HMAC secret
    headers JSONB DEFAULT '{}',
    retry_policy JSONB DEFAULT NULL,
    is_active BOOLEAN DEFAULT true
);

CREATE TABLE webhook_deliveries (
    webhook_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_data JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    http_status INT,
    response_body TEXT,
    error_message TEXT,
    attempt_count INT DEFAULT 0,
    delivered_at TIMESTAMPTZ
);
```

### Implementation

**Webhook Dispatcher** (pseudocode):

```python
import hmac
import hashlib
import httpx

class WebhookDispatcher:
    async def dispatch_event(self, event_type: str, event_data: dict):
        # Get subscribed webhooks
        webhooks = await self.get_webhooks_for_event(event_type)

        for webhook in webhooks:
            # Create delivery record
            delivery_id = await self.create_delivery(webhook.webhook_id, event_type, event_data)

            # Prepare payload
            payload = {
                "event": event_type,
                "data": event_data,
                "timestamp": datetime.utcnow().isoformat(),
                "webhook_id": webhook.webhook_id
            }

            # Generate HMAC signature
            signature = self.generate_signature(webhook.secret, payload)

            # Send webhook
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        webhook.url,
                        json=payload,
                        headers={
                            "X-Webhook-Signature": signature,
                            "X-Webhook-Event": event_type,
                            **webhook.headers
                        },
                        timeout=10.0
                    )

                    # Update delivery
                    await self.update_delivery(
                        delivery_id,
                        status="delivered" if response.status_code < 400 else "failed",
                        http_status=response.status_code,
                        response_body=response.text[:1000]
                    )

            except Exception as e:
                await self.update_delivery(
                    delivery_id,
                    status="failed",
                    error_message=str(e)
                )

    def generate_signature(self, secret: str, payload: dict) -> str:
        """Generate HMAC-SHA256 signature."""
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = hmac.new(
            secret.encode(),
            payload_bytes,
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
```

### Integration Examples

**1. Slack Notification**:

```python
# Register Slack webhook
webhook = {
    "name": "Slack Critical Alerts",
    "url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
    "events": ["command_failed", "approval_rejected", "device_offline"],
    "headers": {"Content-Type": "application/json"}
}

# Event payload transformation for Slack
def to_slack_message(event_type, event_data):
    return {
        "text": f":warning: {event_type}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Event*: {event_type}\n*Device*: {event_data['device_id']}\n*Time*: {event_data['timestamp']}"
                }
            }
        ]
    }
```

**2. PagerDuty Integration**:

```python
webhook = {
    "name": "PagerDuty Incidents",
    "url": "https://events.pagerduty.com/v2/enqueue",
    "events": ["device_offline", "command_failed", "broadcast_failed"],
    "headers": {
        "Authorization": "Token token=YOUR_API_KEY",
        "Content-Type": "application/json"
    }
}

# PagerDuty event format
def to_pagerduty_event(event_type, event_data):
    return {
        "routing_key": "YOUR_ROUTING_KEY",
        "event_action": "trigger",
        "payload": {
            "summary": f"{event_type}: {event_data['device_id']}",
            "severity": "critical" if "failed" in event_type else "warning",
            "source": "rufus-edge",
            "custom_details": event_data
        }
    }
```

**3. Custom API Integration**:

```python
# Verify webhook signature
def verify_signature(payload, signature, secret):
    expected = generate_signature(secret, payload)
    return hmac.compare_digest(signature, expected)

# Webhook receiver endpoint
@app.post("/webhooks/rufus")
async def receive_webhook(request: Request):
    signature = request.headers.get("X-Webhook-Signature")
    payload = await request.json()

    if not verify_signature(payload, signature, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Process event
    event_type = payload["event"]
    event_data = payload["data"]

    # Your custom logic here
    await process_rufus_event(event_type, event_data)

    return {"status": "received"}
```

### API Endpoints

```python
# Register webhook
POST /api/v1/webhooks
{
  "name": "Slack Alerts",
  "url": "https://hooks.slack.com/...",
  "events": ["command_failed", "device_offline"],
  "secret": "your-secret-key"
}

# List webhooks
GET /api/v1/webhooks

# Get webhook deliveries
GET /api/v1/webhooks/{webhook_id}/deliveries

# Test webhook
POST /api/v1/webhooks/{webhook_id}/test

# Delete webhook
DELETE /api/v1/webhooks/{webhook_id}
```

### Event Types

All audit log event types are available:
- `command_*`: created, completed, failed, cancelled
- `broadcast_*`: created, completed, failed
- `approval_*`: requested, approved, rejected, expired
- `device_*`: registered, offline, online, heartbeat
- `schedule_*`: executed, paused, resumed

### Best Practices

1. **Retry Policy**: Use exponential backoff for failed deliveries
2. **Timeout**: 10-second timeout for webhook calls
3. **Security**: Always verify HMAC signatures
4. **Monitoring**: Track webhook success rate
5. **Payload Size**: Limit payload to 100KB

---

## 3. Command Rate Limiting

Protect against command flooding, abuse, and ensure fair usage.

### Database Schema

```sql
CREATE TABLE rate_limit_rules (
    rule_name VARCHAR(100) UNIQUE NOT NULL,
    resource_pattern VARCHAR(200) NOT NULL,  -- "/api/v1/commands*"
    limit_per_window INT NOT NULL,  -- Max requests
    window_seconds INT NOT NULL,  -- Time window
    scope VARCHAR(50) NOT NULL,  -- user, ip, api_key, global
    is_active BOOLEAN DEFAULT true
);

-- Default rules
INSERT INTO rate_limit_rules VALUES
    ('global_api_limit', '/api/v1/*', 1000, 60, 'ip'),  -- 1000 req/min per IP
    ('command_creation_limit', '/api/v1/commands', 100, 60, 'user'),  -- 100 cmd/min per user
    ('approval_limit', '/api/v1/approvals', 50, 60, 'user');  -- 50 approvals/min per user
```

### Implementation

**Rate Limiter Middleware**:

```python
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

class RateLimiter:
    def __init__(self):
        # In-memory cache (use Redis for distributed systems)
        self.cache = defaultdict(lambda: {"count": 0, "reset_at": None})
        self.lock = asyncio.Lock()

    async def check_rate_limit(
        self,
        identifier: str,  # user_id, ip_address, api_key
        resource: str,
        limit: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check if request is within rate limit.

        Returns:
            (allowed, headers): Whether request is allowed + rate limit headers
        """
        async with self.lock:
            key = f"{identifier}:{resource}"
            now = datetime.utcnow()

            # Get or create cache entry
            entry = self.cache[key]

            # Reset if window expired
            if entry["reset_at"] is None or now >= entry["reset_at"]:
                entry["count"] = 0
                entry["reset_at"] = now + timedelta(seconds=window_seconds)

            # Increment counter
            entry["count"] += 1

            # Check limit
            allowed = entry["count"] <= limit
            remaining = max(0, limit - entry["count"])

            headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(int(entry["reset_at"].timestamp()))
            }

            return allowed, headers

# FastAPI middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # Get identifier (user_id or IP)
    user = get_current_user(request)
    identifier = user.get("user_id") if user else request.client.host

    # Get applicable rate limit rule
    rule = await get_rate_limit_rule(request.url.path)

    if rule:
        allowed, headers = await rate_limiter.check_rate_limit(
            identifier=identifier,
            resource=request.url.path,
            limit=rule.limit_per_window,
            window_seconds=rule.window_seconds
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                headers=headers,
                content={"error": "Rate limit exceeded"}
            )

        # Add rate limit headers
        response = await call_next(request)
        for key, value in headers.items():
            response.headers[key] = value
        return response

    return await call_next(request)
```

### Redis Implementation (Production)

```python
import redis.asyncio as redis

class RedisRateLimiter:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)

    async def check_rate_limit(
        self,
        identifier: str,
        resource: str,
        limit: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        key = f"rate_limit:{identifier}:{resource}"

        # Atomic increment with expiry
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = await pipe.execute()

        count = results[0]
        allowed = count <= limit
        remaining = max(0, limit - count)

        # Get TTL for reset time
        ttl = await self.redis.ttl(key)
        reset_at = int(time.time()) + ttl

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at)
        }

        return allowed, headers
```

### Rate Limit Strategies

**1. Fixed Window**:
```python
# Simple: 100 requests per 60 seconds
# Downside: Burst at window boundaries
limit = 100
window = 60
```

**2. Sliding Window** (More accurate):
```python
async def sliding_window_rate_limit(identifier, limit, window):
    now = time.time()
    key = f"rate_limit:{identifier}"

    # Remove old requests outside window
    await redis.zremrangebyscore(key, 0, now - window)

    # Count requests in window
    count = await redis.zcard(key)

    if count < limit:
        # Add current request
        await redis.zadd(key, {str(now): now})
        await redis.expire(key, window)
        return True

    return False
```

**3. Token Bucket** (Allow bursts):
```python
class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate  # tokens per second
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        refill = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + refill)
        self.last_refill = now
```

### Configuration Examples

**Per-User Limits**:
```sql
-- Different limits for different roles
INSERT INTO rate_limit_rules VALUES
    ('admin_commands', '/api/v1/commands', 1000, 60, 'user'),  -- Admin
    ('operator_commands', '/api/v1/commands', 100, 60, 'user'),  -- Operator
    ('viewer_read', '/api/v1/*', 500, 60, 'user');  -- Viewer
```

**Progressive Rate Limiting**:
```sql
-- Stricter limits for failed auth attempts
INSERT INTO rate_limit_rules VALUES
    ('auth_attempts', '/api/v1/auth/login', 5, 300, 'ip');  -- 5 attempts per 5 min

-- Looser limits after successful auth
INSERT INTO rate_limit_rules VALUES
    ('authenticated_api', '/api/v1/*', 10000, 3600, 'user');  -- 10k req/hour
```

### API Endpoints

```python
# Get rate limit status
GET /api/v1/rate-limits/status
{
  "limits": [
    {
      "resource": "/api/v1/commands",
      "limit": 100,
      "remaining": 73,
      "reset_at": "2026-02-04T15:30:00Z"
    }
  ]
}

# Admin: View all rate limit rules
GET /api/v1/admin/rate-limits

# Admin: Update rate limit rule
PUT /api/v1/admin/rate-limits/{rule_name}
{
  "limit_per_window": 200,
  "window_seconds": 60
}
```

### Best Practices

1. **Headers**: Always return `X-RateLimit-*` headers
2. **429 Status**: Use HTTP 429 Too Many Requests
3. **Retry-After**: Include `Retry-After` header
4. **Monitoring**: Track rate limit hits per user/IP
5. **Exemptions**: Allow-list for monitoring services
6. **Graceful Degradation**: Degrade service before hard limits

---

# Tier 5: Enterprise Extensions

## 4. GraphQL API

Powerful query language for flexible data fetching, reducing over-fetching and under-fetching.

### Architecture

```
┌────────────┐
│  GraphQL   │
│  Gateway   │
└────────────┘
      │
      ├──→ Commands Resolver
      ├──→ Devices Resolver
      ├──→ Approvals Resolver
      ├──→ Audit Logs Resolver
      └──→ Schedules Resolver
```

### Schema Design

```graphql
# Types
type Command {
  id: ID!
  commandId: String!
  deviceId: String!
  commandType: String!
  commandData: JSON!
  status: CommandStatus!
  createdAt: DateTime!
  completedAt: DateTime
  retryCount: Int!
  device: Device!
  auditLogs: [AuditLogEntry!]!
}

type Device {
  id: ID!
  deviceId: String!
  deviceType: String!
  deviceName: String
  status: DeviceStatus!
  lastHeartbeat: DateTime
  commands(limit: Int = 10, offset: Int = 0): [Command!]!
  firmware: FirmwareInfo
}

type Approval {
  id: ID!
  approvalId: String!
  commandType: String!
  requestedBy: User!
  status: ApprovalStatus!
  approversRequired: Int!
  approversCount: Int!
  responses: [ApprovalResponse!]!
  expiresAt: DateTime!
}

# Queries
type Query {
  # Commands
  command(id: ID!): Command
  commands(
    deviceId: String
    status: CommandStatus
    limit: Int = 50
    offset: Int = 0
  ): CommandConnection!

  # Devices
  device(id: ID!): Device
  devices(
    status: DeviceStatus
    deviceType: String
    limit: Int = 50
  ): DeviceConnection!

  # Approvals
  approval(id: ID!): Approval
  pendingApprovals(userId: String): [Approval!]!

  # Audit Logs
  auditLogs(
    startTime: DateTime
    endTime: DateTime
    deviceId: String
    eventType: String
    limit: Int = 100
  ): AuditLogConnection!

  # Analytics
  commandStats(timeRange: TimeRange!): CommandStats!
  deviceHealthSummary: DeviceHealthSummary!
}

# Mutations
type Mutation {
  # Commands
  createCommand(input: CreateCommandInput!): CreateCommandPayload!
  cancelCommand(id: ID!): CancelCommandPayload!

  # Approvals
  requestApproval(input: ApprovalRequestInput!): ApprovalPayload!
  approveCommand(approvalId: ID!, comment: String): ApprovalPayload!
  rejectCommand(approvalId: ID!, comment: String): ApprovalPayload!

  # Schedules
  createSchedule(input: ScheduleInput!): SchedulePayload!
  pauseSchedule(id: ID!): SchedulePayload!
  resumeSchedule(id: ID!): SchedulePayload!
}

# Subscriptions (Real-time)
type Subscription {
  commandUpdated(deviceId: String): Command!
  approvalPending: Approval!
  deviceStatusChanged(deviceId: String): Device!
}
```

### Implementation Example (Strawberry)

```python
import strawberry
from typing import List, Optional
from datetime import datetime

@strawberry.type
class Command:
    id: strawberry.ID
    command_id: str
    device_id: str
    command_type: str
    status: str
    created_at: datetime

    @strawberry.field
    async def device(self, info) -> "Device":
        # Resolve device from device_service
        return await info.context.device_service.get_device(self.device_id)

    @strawberry.field
    async def audit_logs(self, info) -> List["AuditLogEntry"]:
        # Resolve audit logs
        return await info.context.audit_service.query_logs(
            AuditQuery(command_id=self.command_id)
        )

@strawberry.type
class Query:
    @strawberry.field
    async def command(self, info, id: strawberry.ID) -> Optional[Command]:
        return await info.context.device_service.get_command(id)

    @strawberry.field
    async def commands(
        self,
        info,
        device_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Command]:
        return await info.context.device_service.list_commands(
            device_id=device_id,
            status=status,
            limit=limit
        )

@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_command(
        self,
        info,
        device_id: str,
        command_type: str,
        command_data: strawberry.scalars.JSON
    ) -> Command:
        command_id = await info.context.device_service.send_command(
            device_id=device_id,
            command_type=command_type,
            command_data=command_data
        )
        return await info.context.device_service.get_command(command_id)

# Create schema
schema = strawberry.Schema(query=Query, mutation=Mutation)

# Add to FastAPI
from strawberry.fastapi import GraphQLRouter
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")
```

### Example Queries

**Get command with device and audit logs**:
```graphql
query GetCommand($id: ID!) {
  command(id: $id) {
    commandId
    commandType
    status
    device {
      deviceId
      deviceName
      status
    }
    auditLogs {
      eventType
      timestamp
      actorId
    }
  }
}
```

**List devices with recent commands**:
```graphql
query ListDevicesWithCommands {
  devices(limit: 10) {
    nodes {
      deviceId
      deviceName
      status
      commands(limit: 5) {
        commandType
        status
        createdAt
      }
    }
  }
}
```

**Complex analytics query**:
```graphql
query DashboardData {
  commandStats(timeRange: LAST_24_HOURS) {
    totalCommands
    successRate
    failureRate
  }

  deviceHealthSummary {
    totalDevices
    onlineCount
    offlineCount
    criticalAlerts
  }

  pendingApprovals(userId: "current-user") {
    approvalId
    commandType
    requestedBy {
      userId
      username
    }
    expiresAt
  }
}
```

### Benefits

1. **Flexible Querying**: Fetch exactly what you need
2. **Reduced API Calls**: Single request for complex data
3. **Type Safety**: Strong typing with auto-generated docs
4. **Real-time**: Subscriptions for live updates
5. **Introspection**: Self-documenting API

### Implementation Guide

```bash
# Install dependencies
pip install strawberry-graphql[fastapi]

# Create schema
python -m strawberry export-schema app:schema > schema.graphql

# GraphQL Playground
http://localhost:8000/graphql
```

---

## 5. Multi-Cloud Deployment

Deploy Ruvon Edge across AWS, Azure, and GCP for redundancy and regional presence.

### Architecture

```
                    ┌─────────────────┐
                    │  Global DNS     │
                    │  (Route 53)     │
                    └─────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
    ┌───────┐          ┌───────┐          ┌───────┐
    │  AWS  │          │ Azure │          │  GCP  │
    │ (US)  │          │ (EU)  │          │ (APAC)│
    └───────┘          └───────┘          └───────┘
        │                   │                   │
    ┌───────┐          ┌───────┐          ┌───────┐
    │ Edge  │          │ Edge  │          │ Edge  │
    │Devices│          │Devices│          │Devices│
    └───────┘          └───────┘          └───────┘
```

### AWS Deployment

**Infrastructure as Code** (Terraform):

```hcl
# main.tf
provider "aws" {
  region = "us-east-1"
}

# VPC
resource "aws_vpc" "ruvon" {
  cidr_block = "10.0.0.0/16"

  tags = {
    Name = "rufus-edge-vpc"
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "ruvon" {
  name = "rufus-edge-cluster"
}

# RDS PostgreSQL
resource "aws_db_instance" "ruvon" {
  identifier        = "rufus-edge-db"
  engine            = "postgres"
  engine_version    = "15.3"
  instance_class    = "db.t3.medium"
  allocated_storage = 100

  db_name  = "ruvon"
  username = "ruvon"
  password = var.db_password

  vpc_security_group_ids = [aws_security_group.db.id]
  db_subnet_group_name   = aws_db_subnet_group.rufus.name

  backup_retention_period = 7
  multi_az               = true

  tags = {
    Name = "rufus-edge-db"
  }
}

# Application Load Balancer
resource "aws_lb" "ruvon" {
  name               = "rufus-edge-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

# ECS Service
resource "aws_ecs_service" "ruvon" {
  name            = "rufus-edge-service"
  cluster         = aws_ecs_cluster.rufus.id
  task_definition = aws_ecs_task_definition.rufus.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  load_balancer {
    target_group_arn = aws_lb_target_group.rufus.arn
    container_name   = "rufus-edge"
    container_port   = 8000
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }
}

# Task Definition
resource "aws_ecs_task_definition" "ruvon" {
  family                   = "rufus-edge"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"

  container_definitions = jsonencode([
    {
      name  = "rufus-edge"
      image = "your-registry/rufus-edge:latest"

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "DATABASE_URL"
          value = "postgresql://${aws_db_instance.rufus.endpoint}/rufus"
        }
      ]

      secrets = [
        {
          name      = "DB_PASSWORD"
          valueFrom = aws_secretsmanager_secret.db_password.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = "/ecs/rufus-edge"
          "awslogs-region"        = "us-east-1"
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])
}
```

### Azure Deployment

**Azure Resource Manager** (ARM template):

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
  "contentVersion": "1.0.0.0",
  "resources": [
    {
      "type": "Microsoft.ContainerInstance/containerGroups",
      "apiVersion": "2021-09-01",
      "name": "rufus-edge",
      "location": "[parameters('location')]",
      "properties": {
        "containers": [
          {
            "name": "rufus-edge-api",
            "properties": {
              "image": "your-registry/rufus-edge:latest",
              "ports": [
                {
                  "port": 8000,
                  "protocol": "TCP"
                }
              ],
              "resources": {
                "requests": {
                  "cpu": 1.0,
                  "memoryInGB": 2.0
                }
              },
              "environmentVariables": [
                {
                  "name": "DATABASE_URL",
                  "secureValue": "[parameters('databaseUrl')]"
                }
              ]
            }
          }
        ],
        "osType": "Linux",
        "ipAddress": {
          "type": "Public",
          "ports": [
            {
              "port": 8000,
              "protocol": "TCP"
            }
          ]
        }
      }
    },
    {
      "type": "Microsoft.DBforPostgreSQL/servers",
      "apiVersion": "2017-12-01",
      "name": "rufus-edge-db",
      "location": "[parameters('location')]",
      "sku": {
        "name": "GP_Gen5_2",
        "tier": "GeneralPurpose",
        "capacity": 2,
        "family": "Gen5"
      },
      "properties": {
        "createMode": "Default",
        "version": "11",
        "administratorLogin": "ruvon",
        "administratorLoginPassword": "[parameters('dbPassword')]",
        "storageProfile": {
          "storageMB": 102400,
          "backupRetentionDays": 7,
          "geoRedundantBackup": "Enabled"
        }
      }
    }
  ]
}
```

### GCP Deployment

**Cloud Run + Cloud SQL**:

```yaml
# cloudbuild.yaml
steps:
  # Build container
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/rufus-edge:$SHORT_SHA', '.']

  # Push to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/rufus-edge:$SHORT_SHA']

  # Deploy to Cloud Run
  - name: 'gcr.io/cloud-builders/gcloud'
    args:
      - 'run'
      - 'deploy'
      - 'rufus-edge'
      - '--image=gcr.io/$PROJECT_ID/rufus-edge:$SHORT_SHA'
      - '--region=us-central1'
      - '--platform=managed'
      - '--allow-unauthenticated'
      - '--set-cloudsql-instances=$PROJECT_ID:us-central1:rufus-edge-db'
      - '--set-env-vars=DATABASE_URL=postgresql://rufus@/rufus?host=/cloudsql/$PROJECT_ID:us-central1:rufus-edge-db'

# Terraform for Cloud SQL
resource "google_sql_database_instance" "ruvon" {
  name             = "rufus-edge-db"
  database_version = "POSTGRES_15"
  region           = "us-central1"

  settings {
    tier = "db-custom-2-7680"

    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.rufus.id
    }
  }
}
```

### Multi-Cloud Database Sync

**Cross-Region Replication**:

```python
# Read replicas for global distribution
primary_db = "postgresql://aws-us-east-1/rufus"
replicas = {
    "us": "postgresql://aws-us-east-1/rufus",
    "eu": "postgresql://azure-eu-west/rufus",
    "apac": "postgresql://gcp-asia-east/rufus"
}

# Route reads to nearest replica
def get_db_connection(region: str):
    return replicas.get(region, primary_db)

# Write to primary, read from replica
async def get_device(device_id: str, region: str):
    db = get_db_connection(region)
    return await db.fetchrow("SELECT * FROM edge_devices WHERE device_id = $1", device_id)
```

### Disaster Recovery

**Backup Strategy**:
- Daily automated backups
- 30-day retention
- Cross-region backup replication
- Point-in-time recovery (PITR)

**Failover Plan**:
1. Health checks detect outage
2. DNS switches to backup region
3. Read replicas promoted to primary
4. Applications reconnect automatically

---

## 6. AI-Powered Anomaly Detection

ML-based fraud detection and anomaly detection for edge devices.

### Architecture

```
Edge Device → Command → Feature Extraction → ML Model → Anomaly Score → Alert
```

### Features for Anomaly Detection

```python
from dataclasses import dataclass
from typing import List

@dataclass
class CommandFeatures:
    # Temporal features
    hour_of_day: int
    day_of_week: int
    is_business_hours: bool
    time_since_last_command: float  # seconds

    # Command features
    command_type: str
    command_frequency: float  # commands per hour
    command_type_distribution: dict  # {type: count}

    # Device features
    device_type: str
    device_age_days: int
    firmware_version: str
    location: str

    # User features
    user_role: str
    user_tenure_days: int
    failed_command_rate: float

    # Network features
    ip_address: str
    is_vpn: bool
    is_known_location: bool

    # Historical features
    avg_commands_per_day: float
    max_commands_per_hour: float
    command_type_entropy: float  # Diversity of command types

def extract_features(command, device, user, history) -> CommandFeatures:
    """Extract features from command context."""
    now = datetime.utcnow()

    return CommandFeatures(
        hour_of_day=now.hour,
        day_of_week=now.weekday(),
        is_business_hours=(9 <= now.hour < 17 and now.weekday() < 5),
        time_since_last_command=(now - history.last_command_time).total_seconds(),
        command_type=command.command_type,
        command_frequency=history.commands_last_hour,
        command_type_distribution=history.command_type_counts,
        device_type=device.device_type,
        device_age_days=(now - device.registered_at).days,
        firmware_version=device.firmware_version,
        location=device.location,
        user_role=user.role,
        user_tenure_days=(now - user.created_at).days,
        failed_command_rate=history.failed_commands / max(history.total_commands, 1),
        ip_address=request.client.host,
        is_vpn=is_vpn_ip(request.client.host),
        is_known_location=request.client.host in user.known_ips,
        avg_commands_per_day=history.total_commands / max(history.active_days, 1),
        max_commands_per_hour=history.max_hourly_commands,
        command_type_entropy=calculate_entropy(history.command_type_counts)
    )
```

### Anomaly Detection Models

**1. Isolation Forest** (Unsupervised):

```python
from sklearn.ensemble import IsolationForest
import numpy as np

class IsolationForestDetector:
    def __init__(self):
        self.model = IsolationForest(
            contamination=0.05,  # 5% expected anomalies
            random_state=42
        )
        self.scaler = StandardScaler()

    def train(self, features: List[CommandFeatures]):
        """Train on historical normal behavior."""
        X = self.features_to_array(features)
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled)

    def predict(self, features: CommandFeatures) -> tuple[bool, float]:
        """
        Predict if command is anomalous.

        Returns:
            (is_anomaly, anomaly_score): Boolean and score (-1 to 1)
        """
        X = self.features_to_array([features])
        X_scaled = self.scaler.transform(X)

        prediction = self.model.predict(X_scaled)[0]  # -1 = anomaly, 1 = normal
        score = self.model.score_samples(X_scaled)[0]  # Lower = more anomalous

        is_anomaly = prediction == -1
        return is_anomaly, float(score)

    def features_to_array(self, features: List[CommandFeatures]) -> np.ndarray:
        """Convert features to numpy array."""
        return np.array([
            [
                f.hour_of_day,
                f.day_of_week,
                int(f.is_business_hours),
                f.time_since_last_command,
                f.command_frequency,
                f.device_age_days,
                int(f.is_vpn),
                int(f.is_known_location),
                f.failed_command_rate,
                f.avg_commands_per_day,
                f.command_type_entropy
            ]
            for f in features
        ])
```

**2. Autoencoder** (Deep Learning):

```python
import torch
import torch.nn as nn

class CommandAutoencoder(nn.Module):
    def __init__(self, input_dim: int, encoding_dim: int = 8):
        super().__init__()

        # Encoder
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Linear(16, encoding_dim)
        )

        # Decoder
        self.decoder = nn.Sequential(
            nn.Linear(encoding_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, input_dim)
        )

    def forward(self, x):
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded

class AutoencoderDetector:
    def __init__(self, input_dim: int, threshold_percentile: float = 95):
        self.model = CommandAutoencoder(input_dim)
        self.threshold = None
        self.threshold_percentile = threshold_percentile

    def train(self, features: List[CommandFeatures], epochs: int = 100):
        """Train autoencoder on normal behavior."""
        X = torch.tensor(self.features_to_array(features), dtype=torch.float32)

        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)
        criterion = nn.MSELoss()

        for epoch in range(epochs):
            self.model.train()
            optimizer.zero_grad()

            reconstructed = self.model(X)
            loss = criterion(reconstructed, X)

            loss.backward()
            optimizer.step()

        # Calculate reconstruction errors for normal data
        self.model.eval()
        with torch.no_grad():
            reconstructed = self.model(X)
            errors = torch.mean((X - reconstructed) ** 2, dim=1)
            self.threshold = torch.quantile(errors, self.threshold_percentile / 100)

    def predict(self, features: CommandFeatures) -> tuple[bool, float]:
        """Predict if command is anomalous based on reconstruction error."""
        X = torch.tensor(self.features_to_array([features]), dtype=torch.float32)

        self.model.eval()
        with torch.no_grad():
            reconstructed = self.model(X)
            error = torch.mean((X - reconstructed) ** 2).item()

        is_anomaly = error > self.threshold.item()
        anomaly_score = float(error / self.threshold.item())  # Normalized score

        return is_anomaly, anomaly_score
```

**3. Ensemble Detector** (Combine multiple models):

```python
class EnsembleAnomalyDetector:
    def __init__(self):
        self.isolation_forest = IsolationForestDetector()
        self.autoencoder = AutoencoderDetector(input_dim=11)
        self.threshold = 0.7  # If 70% of models agree, flag as anomaly

    def train(self, features: List[CommandFeatures]):
        self.isolation_forest.train(features)
        self.autoencoder.train(features)

    def predict(self, features: CommandFeatures) -> tuple[bool, float, dict]:
        """
        Ensemble prediction.

        Returns:
            (is_anomaly, confidence, details)
        """
        # Get predictions from all models
        if_anomaly, if_score = self.isolation_forest.predict(features)
        ae_anomaly, ae_score = self.autoencoder.predict(features)

        # Aggregate predictions
        anomaly_votes = sum([if_anomaly, ae_anomaly])
        total_models = 2

        confidence = anomaly_votes / total_models
        is_anomaly = confidence >= self.threshold

        details = {
            "isolation_forest": {"anomaly": if_anomaly, "score": if_score},
            "autoencoder": {"anomaly": ae_anomaly, "score": ae_score},
            "ensemble_confidence": confidence
        }

        return is_anomaly, confidence, details
```

### Integration with Command Flow

```python
class AnomalyDetectionMiddleware:
    def __init__(self, detector: EnsembleAnomalyDetector):
        self.detector = detector

    async def check_command(
        self,
        command: dict,
        device: dict,
        user: dict
    ) -> tuple[bool, Optional[str]]:
        """
        Check if command is anomalous.

        Returns:
            (allow, reason): Whether to allow command and reason if blocked
        """
        # Extract features
        history = await get_command_history(user["user_id"], device["device_id"])
        features = extract_features(command, device, user, history)

        # Predict anomaly
        is_anomaly, confidence, details = self.detector.predict(features)

        if is_anomaly:
            # Log anomaly
            await log_anomaly(
                command_type=command["command_type"],
                device_id=device["device_id"],
                user_id=user["user_id"],
                anomaly_score=confidence,
                details=details
            )

            # High confidence anomalies are blocked
            if confidence > 0.8:
                return False, f"Command blocked: High anomaly score ({confidence:.2f})"

            # Medium confidence triggers approval
            elif confidence > 0.6:
                # Require manual approval
                await request_approval(command, reason=f"Anomaly detected (score: {confidence:.2f})")
                return False, "Command requires approval due to anomaly detection"

        return True, None

# Use in command creation endpoint
@app.post("/api/v1/commands")
async def create_command(command_data: dict, user: UserContext):
    device = await device_service.get_device(command_data["device_id"])

    # Check for anomalies
    allowed, reason = await anomaly_detector.check_command(command_data, device, user)

    if not allowed:
        raise HTTPException(status_code=403, detail=reason)

    # Create command
    command_id = await device_service.send_command(**command_data)
    return {"command_id": command_id}
```

### Training Pipeline

```python
async def train_anomaly_detector():
    """Periodic training on historical normal behavior."""
    # Get last 30 days of successful commands
    commands = await get_commands(
        start_date=datetime.utcnow() - timedelta(days=30),
        status="completed",
        limit=100000
    )

    # Extract features
    features = []
    for cmd in commands:
        device = await get_device(cmd["device_id"])
        user = await get_user(cmd["user_id"])
        history = await get_command_history(user["user_id"], device["device_id"])

        features.append(extract_features(cmd, device, user, history))

    # Train models
    detector = EnsembleAnomalyDetector()
    detector.train(features)

    # Save model
    save_model(detector, "models/anomaly_detector_v1.pkl")

    logger.info(f"Trained anomaly detector on {len(features)} samples")

# Schedule training weekly
schedule.every().sunday.at("02:00").do(train_anomaly_detector)
```

### Monitoring and Feedback

```python
async def log_anomaly_detection(
    command_id: str,
    is_anomaly: bool,
    confidence: float,
    actual_outcome: str  # "fraud", "normal", "unknown"
):
    """Log detection for model improvement."""
    await db.execute(
        """
        INSERT INTO anomaly_detections (
            command_id, is_anomaly, confidence, actual_outcome, logged_at
        ) VALUES ($1, $2, $3, $4, NOW())
        """,
        command_id, is_anomaly, confidence, actual_outcome
    )

# Calculate model performance
async def evaluate_detector():
    results = await db.fetch(
        """
        SELECT is_anomaly, actual_outcome, COUNT(*) as count
        FROM anomaly_detections
        WHERE actual_outcome IN ('fraud', 'normal')
          AND logged_at > NOW() - INTERVAL '30 days'
        GROUP BY is_anomaly, actual_outcome
        """
    )

    # Calculate precision, recall, F1
    tp = results[(True, 'fraud')]  # True positives
    fp = results[(True, 'normal')]  # False positives
    fn = results[(False, 'fraud')]  # False negatives
    tn = results[(False, 'normal')]  # True negatives

    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = 2 * (precision * recall) / (precision + recall)

    logger.info(f"Anomaly detector performance: P={precision:.3f}, R={recall:.3f}, F1={f1:.3f}")
```

---

## Summary

This document covers 6 advanced features:

**Tier 4 - Production Ready**:
1. ✅ Command Versioning - Track schema evolution
2. ✅ Webhook Notifications - Real-time event integrations
3. ✅ Rate Limiting - Protect against abuse

**Tier 5 - Enterprise Extensions**:
4. ✅ GraphQL API - Flexible querying (foundation provided)
5. ✅ Multi-Cloud - AWS/Azure/GCP deployment (configs provided)
6. ✅ AI Anomaly Detection - ML-based fraud detection (framework provided)

All features are designed to scale with the Ruvon Edge platform and integrate seamlessly with the existing command system.
