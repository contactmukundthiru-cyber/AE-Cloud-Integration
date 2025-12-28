# CloudExport

Production-ready end-to-end cloud rendering system for Adobe After Effects. One-click export from a native UXP panel, render on GPU workers, and download results automatically.

## Features

- **One-Click Cloud Export**: Simple UXP panel integration for After Effects
- **Local-First Philosophy**: Smart optimization analysis before suggesting cloud execution
- **Smart Job Routing**: Automatic GPU class selection (RTX 4090 vs A100) based on composition complexity
- **Cost Estimation**: Accurate pricing based on composition complexity
- **Caching System**: Incremental re-renders for identical manifests/presets
- **Credit System**: Server-side ledger with reservations and settlements
- **WebSocket Progress**: Real-time job status updates
- **Email Notifications**: Download links sent automatically when renders complete

## Repository Structure

- `plugin/` After Effects UXP panel
- `cloudexport/` shared backend/worker modules
- `backend/` FastAPI API + dashboard
- `worker/` GPU render worker
- `infra/` docker-compose + Kubernetes manifests

## Prerequisites

- Adobe After Effects installed on GPU worker hosts
- NVIDIA GPU + NVIDIA Container Toolkit for containerized workers
- Docker and Docker Compose for local deployment
- Node.js 18+ for plugin build

## Local Development

### Backend + Worker (Docker)

```bash
cd infra
docker compose up --build
```

Services:
- API: http://localhost:8000
- Dashboard: http://localhost:8000/dashboard
- MinIO: http://localhost:9001 (user/pass: minioadmin)

### API Key

Default bootstrap API key is `cloudexport-dev-key` (configured in `infra/docker-compose.yml`). Use this in the plugin or dashboard.

### Plugin (UXP)

```bash
cd plugin
npm install
npm run build
```

Load `plugin/dist` as a UXP plugin in After Effects. The `Cloud Export` panel appears under Window > Extensions.
Set `API Base URL` in the panel to `http://localhost:8000` for local development.

### Worker Host Setup

GPU workers must have After Effects installed and `aerender` accessible. Set `AERENDER_PATH` if it is not on the PATH.

Example:

```
export AERENDER_PATH=/opt/Adobe/AfterEffects/aerender
```

## Environment Variables

Backend / Worker:

- `DATABASE_URL`
- `REDIS_URL`
- `S3_ENDPOINT_URL`
- `S3_BUCKET`
- `S3_ACCESS_KEY_ID`
- `S3_SECRET_ACCESS_KEY`
- `S3_USE_SSL` (true/false)
- `JWT_SECRET`
- `API_BASE_URL`
- `DASHBOARD_URL`
- `BOOTSTRAP_API_KEY`
- `GPU_CLASS` (worker only)
- `AERENDER_PATH` (worker only)

Optional email:

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`

Payment + Credits:

- `LEMON_WEBHOOK_SECRET`
- `LEMON_VARIANT_CREDITS` (JSON mapping variant_id to credit amount)
- `LEMON_AUTO_CREATE_USERS` (true/false)

## Cloud Deployment (Kubernetes)

1. Build and push images:

```bash
docker build -t cloudexport/api:latest -f backend/Dockerfile .
docker build -t cloudexport/worker:latest -f worker/Dockerfile .
```

2. Apply manifests:

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml
kubectl apply -f infra/k8s/secret.yaml
kubectl apply -f infra/k8s/postgres.yaml
kubectl apply -f infra/k8s/redis.yaml
kubectl apply -f infra/k8s/minio.yaml
kubectl apply -f infra/k8s/api.yaml
kubectl apply -f infra/k8s/worker.yaml
kubectl apply -f infra/k8s/ingress.yaml
```

3. Update DNS for `api.cloudexport.io` to your ingress load balancer.

## Operational Notes

- Jobs are queued in Redis per GPU class.
- Outputs are stored in S3-compatible storage with encryption.
- Completed results are available via signed URLs and optional email notifications.
- Cache entries enable incremental re-renders for identical manifests + presets.
- Credits are stored in a server-side ledger only; clients can only read balances.

## Credits Security Model

- Credits are ledger entries in the backend (`credit_ledger` table).
- Only backend code can add ledger entries (webhooks, reservations, settlements, admin).
- Job creation reserves credits; completion settles and refunds unused reservation.
- Clients never send credit values; all cost calculations happen server-side.

## Lemon Squeezy Setup

1. In Lemon Squeezy, create a Webhook and set the URL to `https://YOUR_DOMAIN/webhooks/lemon`.
2. Enable events: `order_created` and `subscription_payment_success`.
3. Copy the signing secret and set `LEMON_WEBHOOK_SECRET` in the API environment.
4. Optional: set `LEMON_VARIANT_CREDITS` to map `variant_id` → credit amount (USD). Example:

```bash
LEMON_VARIANT_CREDITS='{\"12345\": 50, \"67890\": 200}'
```

Notes:
- The webhook uses the email from the Lemon event (`user_email` or `email`).
- If `LEMON_AUTO_CREATE_USERS=true`, the backend creates a user and emails an API key when SMTP is configured.

## Admin API Key Issuance

Use the admin-only endpoint to issue or rotate API keys:

`POST /admin/users/api-keys`

Payload:
```json
{
  "userEmail": "user@example.com",
  "rotate": true,
  "createIfMissing": true
}
```

The response includes the plaintext key once. Store it securely.

## After Effects Panel Usage

1. Open a saved project and select a composition.
2. Open Cloud Export panel.
3. Set API key and output folder.
4. Click **Refresh Estimate**.
5. Click **Export in Cloud** and you can close After Effects.

## Local-First API Endpoints

The system provides analysis endpoints that help users optimize locally before suggesting cloud rendering:

- `POST /analyze/local` - Comprehensive local optimization analysis
- `POST /analyze/quick` - Fast analysis for UI responsiveness (no auth required)
- `GET /system/capabilities` - Server's system capabilities
- `GET /modes` - Available execution modes (local_only, smart, cloud_enabled)
- `POST /analyze/prerender` - Pre-render opportunity analysis
- `POST /analyze/cache` - Cache settings recommendations
- `POST /analyze/render-graph` - Render dependency and parallelization analysis

## Troubleshooting

- If the panel cannot find the project file, save the AE project first.
- For render failures, check worker logs (`docker compose logs -f worker`).
- Ensure AE `aerender` is on the worker PATH or configured via `AERENDER_PATH`.

## License

This project is provided as-is. Add your own license file as needed.
