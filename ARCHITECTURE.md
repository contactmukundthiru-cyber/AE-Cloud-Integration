# CloudExport - System Architecture

## Overview

CloudExport is a production-ready cloud rendering system for Adobe After Effects that enables one-click export to cloud GPUs.

## System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           USER'S MACHINE                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    After Effects                                      │   │
│  │  ┌───────────────────────────────────────────────────────────────┐  │   │
│  │  │                CloudExport UXP Panel                           │  │   │
│  │  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │   │
│  │  │  │ Composition │  │    Preset    │  │    Export Button     │ │  │   │
│  │  │  │  Detector   │  │   Selector   │  │   (One-Click Magic)  │ │  │   │
│  │  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │   │
│  │  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │  │   │
│  │  │  │    Cost     │  │     ETA      │  │   Progress Status    │ │  │   │
│  │  │  │  Estimate   │  │   Display    │  │   (Real-time WS)     │ │  │   │
│  │  │  └─────────────┘  └──────────────┘  └──────────────────────┘ │  │   │
│  │  │  ┌───────────────────────────────────────────────────────────┐ │  │   │
│  │  │  │              Project Bundler & Asset Resolver              │ │  │   │
│  │  │  └───────────────────────────────────────────────────────────┘ │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTPS / WSS
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLOUD INFRASTRUCTURE                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         API Gateway (nginx)                          │   │
│  │                    TLS Termination / Rate Limiting                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     FastAPI Backend Cluster                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │    Auth      │  │   Jobs API   │  │  WebSocket   │              │   │
│  │  │   Service    │  │   Service    │  │   Handler    │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │   Pricing    │  │   Storage    │  │  Validator   │              │   │
│  │  │   Engine     │  │   Service    │  │   Service    │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                          Message Queue                               │   │
│  │                    Redis (Pub/Sub + Job Queue)                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      GPU Worker Pool                                 │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │   Worker 1   │  │   Worker 2   │  │   Worker N   │              │   │
│  │  │  (RTX 4090)  │  │  (A100 40G)  │  │  (Scalable)  │              │   │
│  │  │              │  │              │  │              │              │   │
│  │  │  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │              │   │
│  │  │  │  AE    │  │  │  │  AE    │  │  │  │  AE    │  │              │   │
│  │  │  │Headless│  │  │  │Headless│  │  │  │Headless│  │              │   │
│  │  │  └────────┘  │  │  └────────┘  │  │  └────────┘  │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     Object Storage (S3-Compatible)                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │  │   Project    │  │   Render     │  │   Temp       │              │   │
│  │  │   Bundles    │  │   Outputs    │  │   Assets     │              │   │
│  │  │  (Encrypted) │  │  (Encrypted) │  │  (Auto-TTL)  │              │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        PostgreSQL Database                           │   │
│  │  Users │ Jobs │ Billing │ Usage │ Audit Logs                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Export Flow
1. User clicks "Export in Cloud" in AE panel
2. Plugin collects composition, assets, fonts, expressions
3. Plugin creates deterministic archive with manifest
4. Plugin requests cost estimate from backend
5. User confirms (if required)
6. Plugin uploads bundle to signed S3 URL
7. Backend creates job, enqueues to Redis
8. Worker picks up job, downloads bundle
9. Worker renders in headless AE
10. Worker uploads output to S3
11. Backend notifies plugin via WebSocket
12. Plugin downloads result OR user gets email/dashboard link

### Job States
```
CREATED → QUEUED → DOWNLOADING → RENDERING → UPLOADING → COMPLETED
                                     │
                                     └──→ FAILED → RETRY (max 3)
                                            │
                                            └──→ PERMANENTLY_FAILED
```

## Security Model

### Authentication
- API Key (for CLI/automation)
- OAuth 2.0 (for web dashboard)
- JWT tokens for session management

### Data Protection
- All uploads encrypted with AES-256
- TLS 1.3 in transit
- Signed URLs with 1-hour expiry
- Auto-deletion after 7 days (configurable)
- No permanent asset storage
- Audit logs for all operations

## Pricing Model

### Cost Components
- **GPU Time**: $0.50/minute (RTX 4090) to $2.00/minute (A100)
- **Storage**: $0.001/GB/hour
- **Transfer**: $0.05/GB

### Estimation Algorithm
```
estimated_cost = (
    (composition_duration * complexity_factor * gpu_rate) +
    (bundle_size_gb * storage_hours * storage_rate) +
    (estimated_output_gb * transfer_rate)
)
```

### Complexity Factors
- Simple composition (no effects): 1.0x
- Standard effects: 1.5x
- Heavy effects (3D, particles): 3.0x
- Third-party plugins: 2.0x additional

## Render Presets

| Preset | Resolution | Codec | Bitrate | Target |
|--------|------------|-------|---------|--------|
| Web | 1080p | H.264 | 8 Mbps | YouTube/Vimeo |
| Social | 1080p | H.264 | 12 Mbps | Instagram/TikTok |
| High Quality | 4K | ProRes 422 | Variable | Professional |
| Custom | User-defined | User-defined | User-defined | Advanced |

## Plugin Compatibility

### Supported
- Native AE effects
- Essential Graphics
- Expressions (all versions)

### Requires Verification
- Third-party plugins (license check)
- Font availability
- External file references

### Not Supported
- Hardware-specific plugins
- Dongleware without cloud licenses
- External scripts during render

## Technology Stack

### Plugin (UXP)
- TypeScript
- React (for UI)
- Adobe UXP APIs
- Webpack bundler

### Backend
- Python 3.11+
- FastAPI
- SQLAlchemy + Alembic
- Redis
- PostgreSQL
- Celery

### Worker
- Docker containers
- NVIDIA Container Toolkit
- Adobe After Effects (headless)
- Python orchestration

### Infrastructure
- Kubernetes (GKE/EKS)
- Terraform
- Prometheus + Grafana
- AWS S3 / GCS

## File Structure
```
aecloud/
├── plugin/                    # After Effects UXP Plugin
│   ├── src/
│   │   ├── ae/                # AE project + asset collection
│   │   ├── api/               # Backend communication
│   │   ├── utils/             # Bundler, hashing, storage helpers
│   │   └── assets/            # Icons, styles
│   ├── manifest.json          # UXP manifest
│   ├── package.json
│   └── webpack.config.js
├── cloudexport/               # Shared backend/worker modules
│   ├── config.py
│   ├── models.py
│   ├── pricing.py
│   ├── queue.py
│   └── storage.py
├── backend/                   # FastAPI Backend
│   ├── app/
│   │   ├── main.py
│   │   ├── templates/         # Dashboard HTML
│   │   └── static/            # Dashboard assets
│   ├── requirements.txt
│   └── Dockerfile
├── worker/                    # GPU Render Worker
│   ├── worker.py
│   ├── requirements.txt
│   └── Dockerfile
└── infra/                     # Deployment
    ├── docker-compose.yml
    ├── nginx/
    └── k8s/
```
