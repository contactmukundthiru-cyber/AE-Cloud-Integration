from __future__ import annotations
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from cloudexport.config import settings
from cloudexport.database import init_db, SessionLocal
from cloudexport.models import User, Job, JobEvent, Usage, CacheEntry
from cloudexport.schemas import (
    EstimateRequest,
    EstimateResponse,
    UploadRequest,
    UploadResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
    JobResultResponse,
    AuthRequest,
    AuthResponse,
    JobHistoryResponse,
    JobHistoryEntry,
    CreditsResponse,
    CreditLedgerEntry,
    CreditAdjustRequest,
    ApiKeyIssueRequest,
    ApiKeyIssueResponse,
)
from cloudexport.auth import authenticate_api_key, bootstrap_admin, create_access_token, hash_api_key
from cloudexport.pricing import estimate_cost
from cloudexport.storage import ensure_bucket, generate_presigned_put, generate_presigned_get, get_object_size
from cloudexport.queue import enqueue_job, publish_progress, remove_job, stream_job_updates
from cloudexport.compatibility import check_manifest
from cloudexport.utils import hash_manifest, current_month
from cloudexport.credits import get_balances, reserve_credits, settle_job_credits, void_reservation, credit_purchase, manual_adjust
from cloudexport.models import CreditLedger
from cloudexport.emailer import send_email
import hmac
import hashlib
import json
import secrets

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title='CloudExport API', version='1.0.0')
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*']
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    api_key = request.headers.get('X-API-Key')
    if api_key:
        user = authenticate_api_key(db, api_key)
        if user:
            return user
        raise HTTPException(status_code=401, detail='Invalid API key')
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header.split(' ', 1)[1]
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            user_id = payload.get('sub')
        except JWTError:
            raise HTTPException(status_code=401, detail='Invalid token')
        user = db.query(User).filter(User.id == user_id).one_or_none()
        if user:
            return user
    raise HTTPException(status_code=401, detail='Not authenticated')


def get_admin_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail='Admin access required')
    return user


@app.on_event('startup')
def startup():
    init_db()
    ensure_bucket()
    db = SessionLocal()
    bootstrap_admin(db)
    db.close()


@app.get('/healthz')
def health():
    return {'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}


@app.post('/auth', response_model=AuthResponse)
def auth(payload: AuthRequest, db: Session = Depends(get_db)):
    user = authenticate_api_key(db, payload.apiKey)
    if not user:
        raise HTTPException(status_code=401, detail='Invalid API key')
    token = create_access_token(user.id)
    return AuthResponse(accessToken=token)


@app.post('/estimate', response_model=EstimateResponse)
def estimate(payload: EstimateRequest, user: User = Depends(get_current_user)):
    manifest_dict = payload.manifest.model_dump()
    try:
        actual_bundle_size = get_object_size(payload.bundleKey)
    except Exception:
        raise HTTPException(status_code=400, detail='Bundle not found in storage')

    cost, eta, gpu_class, warnings = estimate_cost(
        manifest_dict,
        payload.preset,
        actual_bundle_size,
        payload.customOptions
    )
    compat_warnings, compat_errors = check_manifest(manifest_dict)
    if compat_errors:
        raise HTTPException(status_code=400, detail='; '.join(compat_errors))
    warnings.extend(compat_warnings)
    return EstimateResponse(costUsd=cost, etaSeconds=eta, gpuClass=gpu_class, warnings=warnings)


@app.post('/upload', response_model=UploadResponse)
def upload(payload: UploadRequest, user: User = Depends(get_current_user)):
    bundle_key = f'bundles/{user.id}/{payload.manifestHash}.zip'
    upload_url, headers = generate_presigned_put(bundle_key)
    return UploadResponse(uploadUrl=upload_url, bundleKey=bundle_key, headers=headers)


def ensure_usage_limit(db: Session, user: User, estimate_cost_usd: float):
    month = current_month()
    usage = db.query(Usage).filter(Usage.user_id == user.id, Usage.month == month).one_or_none()
    total_cost = usage.cost_usd if usage else 0.0
    if estimate_cost_usd > user.per_job_max_usd:
        raise HTTPException(status_code=400, detail='Job exceeds per-job max spend.')
    if total_cost + estimate_cost_usd > user.monthly_limit_usd:
        raise HTTPException(status_code=400, detail='Monthly usage limit exceeded.')


@app.post('/jobs/create', response_model=JobCreateResponse)
def create_job(payload: JobCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    manifest_dict = payload.manifest.model_dump()
    manifest_hash = hash_manifest(manifest_dict)
    if manifest_hash != payload.manifestHash:
        raise HTTPException(status_code=400, detail='Manifest hash mismatch.')

    cost, eta, gpu_class, warnings = estimate_cost(
        manifest_dict,
        payload.preset,
        payload.bundleSizeBytes,
        payload.customOptions
    )
    compat_warnings, compat_errors = check_manifest(manifest_dict)
    if compat_errors:
        raise HTTPException(status_code=400, detail='; '.join(compat_errors))
    ensure_usage_limit(db, user, cost)

    if payload.allowCache:
        cache = db.query(CacheEntry).filter(
            CacheEntry.manifest_hash == manifest_hash,
            CacheEntry.preset == payload.preset
        ).one_or_none()
        if cache:
            job = Job(
                user_id=user.id,
                status='COMPLETED',
                preset=payload.preset,
                gpu_class=gpu_class,
                manifest=manifest_dict,
                custom_options=payload.customOptions,
                manifest_hash=manifest_hash,
                project_hash=payload.manifest.project.hash,
                bundle_key=payload.bundleKey,
                bundle_sha256=payload.bundleSha256,
                bundle_size_bytes=payload.bundleSizeBytes,
                result_key=cache.result_key,
                output_name=cache.output_name,
                notification_email=payload.notificationEmail,
                cost_estimate_usd=cost,
                cost_final_usd=cost,
                eta_seconds=0,
                progress_percent=100.0,
                cache_hit=True,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow()
            )
            db.add(job)
            db.commit()
            try:
                reserve_credits(db, user.id, job.id, cost)
            except ValueError:
                raise HTTPException(status_code=400, detail='Insufficient credits')
            settle_job_credits(db, job.id, cost)
            publish_progress(job.id, {
                'jobId': job.id,
                'status': job.status,
                'progressPercent': job.progress_percent
            })
            return JobCreateResponse(
                jobId=job.id,
                status=job.status,
                costUsd=cost,
                etaSeconds=0,
                wsUrl=f"{settings.api_base_url.replace('http', 'ws')}/ws/jobs/{job.id}",
                dashboardUrl=f"{settings.dashboard_url}?jobId={job.id}"
            )

    job = Job(
        user_id=user.id,
        status='QUEUED',
        preset=payload.preset,
        gpu_class=gpu_class,
        manifest=manifest_dict,
        custom_options=payload.customOptions,
        manifest_hash=manifest_hash,
        project_hash=payload.manifest.project.hash,
        bundle_key=payload.bundleKey,
        bundle_sha256=payload.bundleSha256,
        bundle_size_bytes=payload.bundleSizeBytes,
        output_name=payload.outputName,
        notification_email=payload.notificationEmail,
        cost_estimate_usd=cost,
        eta_seconds=eta
    )
    db.add(job)
    db.commit()
    try:
        reserve_credits(db, user.id, job.id, cost)
    except ValueError:
        job.status = 'FAILED'
        job.error_message = 'Insufficient credits'
        db.commit()
        raise HTTPException(status_code=400, detail='Insufficient credits')

    event = JobEvent(job_id=job.id, event_type='QUEUED', message='Job queued')
    db.add(event)
    db.commit()

    publish_progress(job.id, {
        'jobId': job.id,
        'status': job.status,
        'progressPercent': 0
    })
    enqueue_job(job.id, gpu_class)

    return JobCreateResponse(
        jobId=job.id,
        status=job.status,
        costUsd=cost,
        etaSeconds=eta,
        wsUrl=f"{settings.api_base_url.replace('http', 'ws')}/ws/jobs/{job.id}",
        dashboardUrl=f"{settings.dashboard_url}?jobId={job.id}"
    )


@app.get('/jobs/status/{job_id}', response_model=JobStatusResponse)
def job_status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return JobStatusResponse(
        jobId=job.id,
        status=job.status,
        progressPercent=job.progress_percent,
        etaSeconds=job.eta_seconds,
        errorMessage=job.error_message
    )


@app.get('/jobs/result/{job_id}', response_model=JobResultResponse)
def job_result(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    if job.status != 'COMPLETED' or not job.result_key:
        raise HTTPException(status_code=400, detail='Job not complete')
    url = generate_presigned_get(job.result_key)
    size_bytes = get_object_size(job.result_key)
    return JobResultResponse(downloadUrl=url, filename=job.output_name, sizeBytes=size_bytes)


@app.post('/jobs/cancel/{job_id}')
def cancel_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == user.id).one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    job.cancel_requested = True
    if job.status == 'QUEUED':
        remove_job(job.id, job.gpu_class)
        job.status = 'CANCELLED'
        job.progress_percent = 0
        job.finished_at = datetime.utcnow()
        db.commit()
        void_reservation(db, job.id, 'cancelled')
        publish_progress(job.id, {
            'jobId': job.id,
            'status': 'CANCELLED',
            'progressPercent': 0
        })
    else:
        db.commit()
    return {'status': 'cancel_requested'}


@app.get('/jobs/history', response_model=JobHistoryResponse)
def job_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.user_id == user.id).order_by(Job.created_at.desc()).limit(50).all()
    entries = [
        JobHistoryEntry(
            jobId=job.id,
            status=job.status,
            preset=job.preset,
            createdAt=job.created_at.isoformat(),
            costUsd=job.cost_estimate_usd,
            outputName=job.output_name
        ) for job in jobs
    ]
    return JobHistoryResponse(jobs=entries)


@app.get('/credits', response_model=CreditsResponse)
def get_credits(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    balances = get_balances(db, user.id)
    entries = db.query(CreditLedger).filter(
        CreditLedger.user_id == user.id
    ).order_by(CreditLedger.created_at.desc()).limit(100).all()
    ledger = [
        CreditLedgerEntry(
            entryType=entry.entry_type,
            status=entry.status,
            amountUsd=entry.amount_usd,
            jobId=entry.job_id,
            externalId=entry.external_id,
            createdAt=entry.created_at.isoformat()
        )
        for entry in entries
    ]
    return CreditsResponse(
        postedBalanceUsd=balances.posted_usd,
        reservedUsd=balances.reserved_usd,
        availableUsd=balances.available_usd,
        ledger=ledger
    )


@app.post('/admin/credits/adjust')
def admin_adjust_credits(
    payload: CreditAdjustRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    if not payload.userEmail and not payload.userId:
        raise HTTPException(status_code=400, detail='userEmail or userId required')
    if payload.userEmail:
        target = db.query(User).filter(User.email == payload.userEmail).one_or_none()
    else:
        target = db.query(User).filter(User.id == payload.userId).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail='User not found')

    manual_adjust(
        db,
        target.id,
        payload.amountUsd,
        payload.reason,
        external_id=payload.idempotencyKey
    )
    return {'status': 'ok'}


@app.post('/admin/users/api-keys', response_model=ApiKeyIssueResponse)
def admin_issue_api_key(
    payload: ApiKeyIssueRequest,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    if not payload.userEmail and not payload.userId:
        raise HTTPException(status_code=400, detail='userEmail or userId required')
    if payload.userEmail:
        target = db.query(User).filter(User.email == payload.userEmail).one_or_none()
    else:
        target = db.query(User).filter(User.id == payload.userId).one_or_none()

    if not target and not payload.createIfMissing:
        raise HTTPException(status_code=404, detail='User not found')

    if not target:
        api_key = secrets.token_urlsafe(32)
        target = User(
            email=payload.userEmail,
            api_key_hash=hash_api_key(api_key),
            api_key_hint=api_key[-6:],
            is_active=True
        )
        db.add(target)
        db.commit()
        return ApiKeyIssueResponse(
            userId=target.id,
            email=target.email,
            apiKey=api_key,
            apiKeyHint=target.api_key_hint
        )

    if not payload.rotate and target.api_key_hash:
        raise HTTPException(status_code=400, detail='API key already exists; set rotate=true to rotate')

    api_key = secrets.token_urlsafe(32)
    target.api_key_hash = hash_api_key(api_key)
    target.api_key_hint = api_key[-6:]
    db.commit()
    return ApiKeyIssueResponse(
        userId=target.id,
        email=target.email,
        apiKey=api_key,
        apiKeyHint=target.api_key_hint
    )


def _verify_lemon_signature(secret: str, signature: str, payload: bytes) -> bool:
    digest = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _parse_lemon_amount_usd(attributes: dict) -> float:
    if 'total_usd' in attributes:
        return float(attributes['total_usd'])
    if 'total' in attributes and 'currency' in attributes:
        if str(attributes['currency']).upper() != 'USD':
            raise ValueError('Unsupported currency')
        return float(attributes['total']) / 100.0
    if 'subtotal' in attributes and 'currency' in attributes:
        if str(attributes['currency']).upper() != 'USD':
            raise ValueError('Unsupported currency')
        return float(attributes['subtotal']) / 100.0
    raise ValueError('Missing payment amount')


@app.post('/webhooks/lemon')
async def lemon_webhook(request: Request, db: Session = Depends(get_db)):
    secret = settings.lemon_webhook_secret
    if not secret:
        raise HTTPException(status_code=500, detail='Webhook not configured')

    body = await request.body()
    signature = request.headers.get('X-Signature') or request.headers.get('X-Lemon-Squeezy-Signature')
    if not signature or not _verify_lemon_signature(secret, signature, body):
        raise HTTPException(status_code=401, detail='Invalid signature')

    payload = json.loads(body.decode('utf-8'))
    event = payload.get('meta', {}).get('event_name')
    data = payload.get('data', {})
    attributes = data.get('attributes', {})
    if event not in {'order_created', 'subscription_payment_success'}:
        return {'status': 'ignored'}

    external_id = data.get('id')
    email = attributes.get('user_email') or attributes.get('email')
    if not email or not external_id:
        raise HTTPException(status_code=400, detail='Missing email or id')

    existing = db.query(CreditLedger).filter(CreditLedger.external_id == str(external_id)).one_or_none()
    if existing:
        return {'status': 'ok'}

    try:
        amount_usd = _parse_lemon_amount_usd(attributes)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    variant_id = attributes.get('variant_id')
    credits = amount_usd
    try:
        variant_map = json.loads(settings.lemon_variant_credits or '{}')
        if variant_id and str(variant_id) in variant_map:
            credits = float(variant_map[str(variant_id)])
    except json.JSONDecodeError:
        pass

    user = db.query(User).filter(User.email == email).one_or_none()
    if not user:
        if not settings.lemon_auto_create_users:
            raise HTTPException(status_code=404, detail='User not found')
        api_key = secrets.token_urlsafe(32)
        user = User(
            email=email,
            api_key_hash=hash_api_key(api_key),
            api_key_hint=api_key[-6:],
            is_active=True
        )
        db.add(user)
        db.commit()
        if settings.smtp_host and settings.smtp_user:
            send_email(
                email,
                'Your CloudExport API Key',
                f'Your API key: {api_key}'
            )

    credit_purchase(db, user.id, credits, str(external_id), 'lemon')
    return {'status': 'ok'}


@app.websocket('/ws/jobs/{job_id}')
async def job_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    try:
        async for message in stream_job_updates(job_id):
            await websocket.send_text(message)
    except WebSocketDisconnect:
        return


@app.get('/dashboard', response_class=HTMLResponse)
def dashboard():
    with open(BASE_DIR / 'templates' / 'dashboard.html', 'r', encoding='utf-8') as file:
        return HTMLResponse(file.read())


# =============================================================================
# LOCAL-FIRST OPTIMIZATION ENDPOINTS
# These endpoints support the local-first philosophy by providing analysis
# and recommendations without requiring cloud execution.
# =============================================================================

from cloudexport.local_optimizer import get_optimization_report, quick_estimate
from cloudexport.render_graph import analyze_manifest_for_optimization
from cloudexport.hardware import get_system_capabilities, estimate_local_render_time as hw_estimate_local
from cloudexport.cache_manager import get_cache_recommendation
from cloudexport.execution_modes import get_execution_plan, get_mode_options
from cloudexport.prerender import analyze_for_prerender
from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class LocalAnalysisRequest(BaseModel):
    manifest: Dict[str, Any]
    mode: str = 'smart'  # local_only, smart, cloud_enabled
    includeCloud: bool = True


class LocalAnalysisResponse(BaseModel):
    recommendedMode: str
    headline: str
    reasoning: str
    details: List[str]
    hardwareSummary: str
    localEstimate: Dict[str, Any]
    cloudEstimate: Optional[Dict[str, Any]]
    suggestions: List[Dict[str, Any]]
    executionOptions: List[Dict[str, Any]]
    renderGraph: Optional[Dict[str, Any]]
    cacheRecommendation: Optional[Dict[str, Any]]
    prerenderAnalysis: Optional[Dict[str, Any]]


@app.post('/analyze/local', response_model=LocalAnalysisResponse)
def analyze_local(payload: LocalAnalysisRequest, user: User = Depends(get_current_user)):
    """
    Perform comprehensive local optimization analysis.

    This is the core local-first endpoint that provides:
    - Accurate local render time estimates
    - Hardware-aware optimization suggestions
    - Render graph analysis for parallelization
    - Cache recommendations
    - Pre-render opportunities

    Users with no cloud budget should find this analysis valuable on its own.
    """
    manifest = payload.manifest
    mode = payload.mode

    # Get full optimization report
    report = get_optimization_report(manifest, mode)

    # Get render graph analysis
    render_graph = analyze_manifest_for_optimization(manifest)

    # Get cache recommendation
    system_caps = get_system_capabilities().to_dict()
    cache_rec = get_cache_recommendation(manifest, system_caps)

    # Get pre-render analysis
    prerender = analyze_for_prerender(manifest)

    return LocalAnalysisResponse(
        recommendedMode=report['recommended_mode'],
        headline=report['headline'],
        reasoning=report['reasoning'],
        details=report['details'],
        hardwareSummary=report['hardware_summary'] if 'hardware_summary' in report else '',
        localEstimate=report['local_estimate'],
        cloudEstimate=report.get('cloud_estimate'),
        suggestions=report['suggestions'],
        executionOptions=[],  # Would be populated from execution_modes
        renderGraph=render_graph,
        cacheRecommendation=cache_rec,
        prerenderAnalysis=prerender
    )


@app.post('/analyze/quick')
def analyze_quick(payload: LocalAnalysisRequest):
    """
    Quick analysis for fast UI responsiveness.
    No authentication required for this lightweight endpoint.
    """
    manifest = payload.manifest
    result = quick_estimate(manifest)
    return result


@app.get('/system/capabilities')
def system_capabilities():
    """
    Get server's system capabilities for reference.
    Useful for comparing local vs cloud hardware.
    """
    caps = get_system_capabilities()
    return caps.to_dict()


@app.get('/modes')
def get_modes():
    """
    Get available execution modes.

    Returns the three modes with their descriptions:
    - local_only: No cloud, maximum local optimization
    - smart: System recommends optimal execution
    - cloud_enabled: Aggressive cloud usage
    """
    return get_mode_options()


@app.post('/analyze/prerender')
def analyze_prerender(payload: LocalAnalysisRequest, user: User = Depends(get_current_user)):
    """
    Analyze composition for pre-render opportunities.

    Identifies:
    - Static layers that can be pre-rendered once
    - Expression-heavy layers
    - Heavy effects that benefit from caching
    """
    manifest = payload.manifest
    analysis = analyze_for_prerender(manifest)
    return analysis


@app.post('/analyze/cache')
def analyze_cache(payload: LocalAnalysisRequest, user: User = Depends(get_current_user)):
    """
    Get cache settings recommendations.

    Provides:
    - Optimal RAM preview allocation
    - Disk cache size recommendations
    - Cache strategy (conservative/balanced/aggressive)
    """
    manifest = payload.manifest
    system_caps = get_system_capabilities().to_dict()
    recommendation = get_cache_recommendation(manifest, system_caps)
    return recommendation


@app.post('/analyze/render-graph')
def analyze_render_graph(payload: LocalAnalysisRequest, user: User = Depends(get_current_user)):
    """
    Analyze composition render graph.

    Provides:
    - Dependency analysis
    - Parallelization opportunities
    - Critical path identification
    - Chunk recommendations
    """
    manifest = payload.manifest
    analysis = analyze_manifest_for_optimization(manifest)
    return analysis
