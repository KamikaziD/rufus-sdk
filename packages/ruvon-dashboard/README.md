# Ruvon Edge Dashboard

A production-grade React/Next.js 14 management UI for the Ruvon Edge control plane.

## Stack

| Layer | Library |
|-------|---------|
| Framework | Next.js 14 App Router |
| Auth | next-auth v5 + Keycloak OIDC |
| UI | shadcn/ui primitives + Tailwind CSS |
| Server state | TanStack Query v5 |
| Forms | React Hook Form + Zod |
| Charts | Recharts |
| DAG | Custom SVG renderer |

## Quick Start

### Prerequisites
- Node.js 20+
- Ruvon API server running at `localhost:8000`
- Keycloak running at `localhost:8080` (see `docker/docker-compose.yml`)

### Local Dev

```bash
cd packages/ruvon-dashboard
cp .env.example .env.local
# Edit .env.local — set NEXTAUTH_SECRET + confirm URLs
npm install
npm run dev
# Open http://localhost:3000
```

### With Docker Compose

```bash
cd docker
docker compose up -d    # starts postgres + keycloak + ruvon-server
cd ../packages/ruvon-dashboard
npm run dev             # Next.js dev server
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXTAUTH_URL` | Yes | Dashboard base URL (e.g. `http://localhost:3000`) |
| `NEXTAUTH_SECRET` | Yes | Random 32-byte secret for JWT signing |
| `KEYCLOAK_CLIENT_ID` | Yes | `ruvon-dashboard` |
| `KEYCLOAK_ISSUER` | Yes | `http://localhost:8080/realms/ruvon` |
| `NEXT_PUBLIC_RUVON_API_URL` | Yes | Ruvon API URL (e.g. `http://localhost:8000`) |

## Seed Users (dev)

| Username | Password | Role |
|----------|----------|------|
| `admin` | `ruvon-dev` | `SUPER_ADMIN` |
| `fleet` | `ruvon-dev` | `FLEET_MANAGER` |
| `operator` | `ruvon-dev` | `WORKFLOW_OPERATOR` |
| `auditor` | `ruvon-dev` | `AUDITOR` |
| `readonly` | `ruvon-dev` | `READ_ONLY` |

## RBAC

| Page | Minimum Role |
|------|-------------|
| `/` Overview | Any |
| `/workflows` | Any |
| `/workflows/new` | `WORKFLOW_OPERATOR` |
| `/approvals` | `WORKFLOW_OPERATOR` |
| `/devices` | Any |
| `/policies` | `FLEET_MANAGER` |
| `/audit` | `AUDITOR` |
| `/admin` | `SUPER_ADMIN` |

## Build

```bash
npm run build
npm start
```
