export type Preset = 'web' | 'social' | 'high_quality' | 'custom';

// Execution modes - user selectable
export type ExecutionMode = 'local_only' | 'smart' | 'cloud_enabled';

export interface ManifestAsset {
  id: string;
  originalPath: string;
  zipPath: string;
  sizeBytes: number;
  sha256: string;
  lastModified: string;
}

export interface ManifestComposition {
  name: string;
  durationSeconds: number;
  fps: number;
  width: number;
  height: number;
  workAreaStart: number;
  workAreaDuration: number;
}

export interface ManifestProject {
  name: string;
  path: string;
  hash: string;
  sizeBytes: number;
  saved: boolean;
}

// Enhanced manifest with deep analysis
export interface Manifest {
  schemaVersion: number;
  project: ManifestProject;
  composition: ManifestComposition;
  assets: ManifestAsset[];
  fonts: string[];
  effects: string[];
  expressionsCount: number;
  createdAt: string;
  // Extended analysis data
  analysis?: CompositionAnalysis;
}

// Deep composition analysis for optimization
export interface CompositionAnalysis {
  layerCount: number;
  precompCount: number;
  nestedDepth: number;
  heavyEffects: string[];
  staticLayers: number;
  expressionLayers: number;
  parallelizableGroups: number;
  estimatedComplexity: number; // 1-10 scale
  bottlenecks: string[];
  optimizationHints: string[];
}

// Local render estimate
export interface LocalEstimate {
  totalSeconds: number;
  totalFormatted: string;
  perFrameMs: number;
  frameCount: number;
  bottleneck: string;
  bottleneckDetail: string;
  speedupFactor: number;
  optimizations: string[];
  hardwareTier: string;
}

// Cloud render estimate
export interface CloudEstimate {
  totalSeconds: number;
  totalFormatted: string;
  costUsd: number;
  gpuClass: string;
  speedupVsLocal: number;
}

// Execution option for UI display
export interface ExecutionOption {
  decision: string;
  label: string;
  description: string;
  estimatedSeconds: number;
  estimatedCostUsd: number;
  details: string[];
  pros: string[];
  cons: string[];
  isRecommended: boolean;
  recommendationReason: string;
  canExecute: boolean;
  blockedReason?: string;
}

// Complete optimization analysis result
export interface OptimizationAnalysis {
  mode: ExecutionMode;
  recommendedMode: ExecutionMode;
  headline: string;
  reasoning: string;
  details: string[];
  hardwareSummary: string;
  localEstimate: LocalEstimate;
  cloudEstimate?: CloudEstimate;
  suggestions: OptimizationSuggestion[];
  executionOptions: ExecutionOption[];
}

export interface OptimizationSuggestion {
  category: string;
  title: string;
  description: string;
  impact: string;
  automatic: boolean;
  actionId?: string;
}

// Cache recommendation
export interface CacheRecommendation {
  strategy: string;
  ramPreviewMb: number;
  diskCacheGb: number;
  prerenderEnabled: boolean;
  reasoning: string;
  estimatedSpeedup: number;
}

export interface EstimateRequest {
  manifest: Manifest;
  preset: Preset;
  bundleSizeBytes: number;
  customOptions?: Record<string, unknown> | null;
}

export interface EstimateResponse {
  costUsd: number;
  etaSeconds: number;
  gpuClass: string;
  warnings: string[];
}

// Enhanced estimate response with local analysis
export interface FullEstimateResponse extends EstimateResponse {
  localEstimate?: LocalEstimate;
  cloudEstimate?: CloudEstimate;
  analysis?: OptimizationAnalysis;
  cacheRecommendation?: CacheRecommendation;
}

export interface UploadResponse {
  uploadUrl: string;
  bundleKey: string;
  headers: Record<string, string>;
}

export interface JobCreateResponse {
  jobId: string;
  status: string;
  costUsd: number;
  etaSeconds: number;
  wsUrl: string;
  dashboardUrl: string;
}

export interface JobStatusResponse {
  jobId: string;
  status: string;
  progressPercent: number;
  etaSeconds: number;
  errorMessage?: string;
}

export interface JobResultResponse {
  downloadUrl: string;
  filename: string;
  sizeBytes: number;
}

export interface Settings {
  apiBaseUrl: string;
  apiKey: string;
  outputDirUrl: string;
  notificationEmail: string;
  allowCache: boolean;
  // New local-first settings
  executionMode: ExecutionMode;
  localRenderEnabled: boolean;
  maxCloudCostPerJob: number;
  enablePrerender: boolean;
  cacheStrategy: string;
}
