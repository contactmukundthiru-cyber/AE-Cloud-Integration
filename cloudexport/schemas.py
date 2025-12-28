from pydantic import BaseModel, Field
from typing import List, Optional


class ManifestAsset(BaseModel):
    id: str
    originalPath: str
    zipPath: str
    sizeBytes: int
    sha256: str
    lastModified: str


class ManifestComposition(BaseModel):
    name: str
    durationSeconds: float
    fps: float
    width: int
    height: int
    workAreaStart: float
    workAreaDuration: float


class ManifestProject(BaseModel):
    name: str
    path: str
    hash: str
    sizeBytes: int
    saved: bool


class Manifest(BaseModel):
    schemaVersion: int
    project: ManifestProject
    composition: ManifestComposition
    assets: List[ManifestAsset]
    fonts: List[str]
    effects: List[str]
    expressionsCount: int
    createdAt: str


class EstimateRequest(BaseModel):
    manifest: Manifest
    preset: str
    bundleSizeBytes: int
    customOptions: Optional[dict] = None


class EstimateResponse(BaseModel):
    costUsd: float
    etaSeconds: int
    gpuClass: str
    warnings: List[str]


class UploadRequest(BaseModel):
    bundleSha256: str
    bundleSizeBytes: int
    projectHash: str
    manifestHash: str


class UploadResponse(BaseModel):
    uploadUrl: str
    bundleKey: str
    headers: dict


class JobCreateRequest(BaseModel):
    bundleKey: str
    bundleSha256: str
    bundleSizeBytes: int
    manifestHash: str
    manifest: Manifest
    preset: str
    allowCache: bool = True
    outputName: str
    notificationEmail: Optional[str] = None
    customOptions: Optional[dict] = None


class JobCreateResponse(BaseModel):
    jobId: str
    status: str
    costUsd: float
    etaSeconds: int
    wsUrl: str
    dashboardUrl: str


class JobStatusResponse(BaseModel):
    jobId: str
    status: str
    progressPercent: float
    etaSeconds: int
    errorMessage: Optional[str] = None


class JobResultResponse(BaseModel):
    downloadUrl: str
    filename: str
    sizeBytes: int


class AuthRequest(BaseModel):
    apiKey: str = Field(..., min_length=12)


class AuthResponse(BaseModel):
    accessToken: str
    tokenType: str = 'bearer'


class JobHistoryEntry(BaseModel):
    jobId: str
    status: str
    preset: str
    createdAt: str
    costUsd: float
    outputName: str


class JobHistoryResponse(BaseModel):
    jobs: List[JobHistoryEntry]


class CreditLedgerEntry(BaseModel):
    entryType: str
    status: str
    amountUsd: float
    jobId: Optional[str] = None
    externalId: Optional[str] = None
    createdAt: str


class CreditsResponse(BaseModel):
    postedBalanceUsd: float
    reservedUsd: float
    availableUsd: float
    ledger: List[CreditLedgerEntry]


class CreditAdjustRequest(BaseModel):
    userEmail: Optional[str] = None
    userId: Optional[str] = None
    amountUsd: float
    reason: str
    idempotencyKey: Optional[str] = None


class ApiKeyIssueRequest(BaseModel):
    userEmail: Optional[str] = None
    userId: Optional[str] = None
    rotate: bool = True
    createIfMissing: bool = False


class ApiKeyIssueResponse(BaseModel):
    userId: str
    email: str
    apiKey: str
    apiKeyHint: str
