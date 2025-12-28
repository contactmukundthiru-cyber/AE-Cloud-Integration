/**
 * Local Analysis Engine
 *
 * Performs all optimization analysis locally without server calls.
 * This is the heart of the local-first philosophy - providing value
 * even when completely offline.
 *
 * "This product is successful if a user with no cloud budget,
 * on a mid-range laptop, using Local Only mode...
 * still experiences noticeable speedups, predictability, confidence."
 */

import {
  Manifest,
  CompositionAnalysis,
  LocalEstimate,
  OptimizationAnalysis,
  OptimizationSuggestion,
  ExecutionOption,
  ExecutionMode,
  CacheRecommendation
} from '../types';
import { analyzeComposition, estimatePerFrameTime } from './collector';

// Execution mode configurations
const MODE_LABELS: Record<ExecutionMode, { label: string; description: string; icon: string }> = {
  local_only: {
    label: 'Local Only',
    description: 'All rendering on your machine. No cloud costs.',
    icon: 'computer'
  },
  smart: {
    label: 'Smart',
    description: 'System recommends optimal execution. You decide.',
    icon: 'auto_awesome'
  },
  cloud_enabled: {
    label: 'Cloud Enabled',
    description: 'Use cloud for faster renders and to free your machine.',
    icon: 'cloud'
  }
};

/**
 * Detect local system capabilities
 * Note: In UXP, we have limited system access, so we use heuristics
 */
export function detectLocalCapabilities(): {
  estimatedCores: number;
  hasGpu: boolean;
  estimatedRamGb: number;
  tier: string;
} {
  // UXP doesn't give us direct hardware access
  // We make reasonable assumptions based on AE being able to run
  return {
    estimatedCores: 4, // Minimum for AE
    hasGpu: true, // Assume GPU present if AE runs
    estimatedRamGb: 16, // Reasonable assumption
    tier: 'standard' // Conservative default
  };
}

/**
 * Format duration in human-readable form
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  } else if (seconds < 3600) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs ? `${mins}m ${secs}s` : `${mins}m`;
  } else {
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins ? `${hours}h ${mins}m` : `${hours}h`;
  }
}

/**
 * Calculate local render estimate based on manifest and analysis
 */
export function calculateLocalEstimate(manifest: Manifest, analysis?: CompositionAnalysis): LocalEstimate {
  const comp = manifest.composition;
  const fps = comp.fps || 30;
  const duration = comp.durationSeconds || 0;
  const frameCount = Math.round(duration * fps);

  // Get or perform analysis
  const a = analysis || manifest.analysis || analyzeComposition();

  // Calculate per-frame time
  const perFrameMs = estimatePerFrameTime(a);

  // Base render time
  let baseSeconds = (perFrameMs * frameCount) / 1000;

  // Apply optimization speedups
  let speedupFactor = 1.0;
  const optimizations: string[] = [];

  // Multi-core optimization (if AE 2022+)
  if (a.parallelizableGroups > 1) {
    const coreSpeedup = Math.min(a.parallelizableGroups, 4) * 0.7;
    speedupFactor *= coreSpeedup;
    optimizations.push('Parallel rendering');
  }

  // Static layer pre-render
  if (a.staticLayers > 5) {
    speedupFactor *= 1.2;
    optimizations.push('Static pre-render');
  }

  // GPU acceleration
  const caps = detectLocalCapabilities();
  if (caps.hasGpu && a.heavyEffects.length > 0) {
    speedupFactor *= 1.3;
    optimizations.push('GPU acceleration');
  }

  // Cache benefits (estimated for subsequent renders)
  if (manifest.effects.length > 0) {
    speedupFactor *= 1.1;
    optimizations.push('Disk caching');
  }

  const optimizedSeconds = baseSeconds / speedupFactor;

  // Determine bottleneck
  let bottleneck = 'cpu';
  let bottleneckDetail = 'Standard CPU-bound render';

  if (a.heavyEffects.length > 3) {
    bottleneck = 'effects';
    bottleneckDetail = `${a.heavyEffects.length} heavy effects impacting render time`;
  } else if (a.expressionLayers > 10) {
    bottleneck = 'expressions';
    bottleneckDetail = `${manifest.expressionsCount} expressions evaluating per frame`;
  } else if (comp.width > 3840) {
    bottleneck = 'resolution';
    bottleneckDetail = `High resolution (${comp.width}x${comp.height}) increases processing`;
  }

  return {
    totalSeconds: optimizedSeconds,
    totalFormatted: formatDuration(optimizedSeconds),
    perFrameMs: Math.round(perFrameMs / speedupFactor),
    frameCount,
    bottleneck,
    bottleneckDetail,
    speedupFactor: Math.round(speedupFactor * 10) / 10,
    optimizations,
    hardwareTier: caps.tier
  };
}

/**
 * Generate optimization suggestions based on analysis
 */
export function generateSuggestions(manifest: Manifest, analysis: CompositionAnalysis): OptimizationSuggestion[] {
  const suggestions: OptimizationSuggestion[] = [];

  // Pre-render static layers
  if (analysis.staticLayers > 5) {
    suggestions.push({
      category: 'performance',
      title: 'Pre-render Static Layers',
      description: `${analysis.staticLayers} static layers can be pre-rendered once to speed up iteration`,
      impact: 'high',
      automatic: true,
      actionId: 'prerender_static'
    });
  }

  // Parallel rendering
  if (analysis.parallelizableGroups > 1) {
    suggestions.push({
      category: 'performance',
      title: 'Parallel Frame Rendering',
      description: `${analysis.parallelizableGroups} layer groups can render in parallel with multi-frame rendering`,
      impact: 'high',
      automatic: true,
      actionId: 'enable_multiframe'
    });
  }

  // Expression optimization
  if (manifest.expressionsCount > 50) {
    suggestions.push({
      category: 'workflow',
      title: 'Expression-Heavy Composition',
      description: `${manifest.expressionsCount} expressions detected. Consider pre-composing expression-heavy layers`,
      impact: 'medium',
      automatic: false
    });
  }

  // Heavy effects
  if (analysis.heavyEffects.length > 0) {
    suggestions.push({
      category: 'performance',
      title: 'Heavy Effects Detected',
      description: `${analysis.heavyEffects.length} heavy effects: ${analysis.heavyEffects.slice(0, 2).join(', ')}. Pre-render these layers for faster preview`,
      impact: 'high',
      automatic: true,
      actionId: 'prerender_effects'
    });
  }

  // Deep nesting
  if (analysis.nestedDepth > 3) {
    suggestions.push({
      category: 'workflow',
      title: 'Deep Precomp Nesting',
      description: `${analysis.nestedDepth} levels of nesting. Consider flattening for better cache efficiency`,
      impact: 'medium',
      automatic: false
    });
  }

  // Precomp pre-rendering
  if (analysis.precompCount > 3) {
    suggestions.push({
      category: 'workflow',
      title: 'Multiple Precomps',
      description: `${analysis.precompCount} precomps found. Pre-render stable ones for faster main comp rendering`,
      impact: 'medium',
      automatic: true,
      actionId: 'prerender_precomps'
    });
  }

  // RAM preview optimization
  const comp = manifest.composition;
  const frameCount = Math.round(comp.durationSeconds * comp.fps);
  if (frameCount > 300) {
    suggestions.push({
      category: 'workflow',
      title: 'Long Composition',
      description: 'Consider increasing RAM preview allocation or working with proxies',
      impact: 'low',
      automatic: false
    });
  }

  return suggestions;
}

/**
 * Get cache settings recommendation
 */
export function getCacheRecommendation(manifest: Manifest, analysis: CompositionAnalysis): CacheRecommendation {
  const comp = manifest.composition;
  const duration = comp.durationSeconds || 0;
  const effectCount = manifest.effects.length;
  const exprCount = manifest.expressionsCount;

  // Calculate recommended settings
  let ramPreviewMb = 4096; // Default 4GB
  let diskCacheGb = 20; // Default 20GB
  let strategy = 'balanced';

  // Adjust based on composition
  if (effectCount > 10 || exprCount > 50) {
    ramPreviewMb = 8192;
    diskCacheGb = 50;
    strategy = 'aggressive';
  } else if (effectCount < 5 && exprCount < 20 && duration < 60) {
    ramPreviewMb = 2048;
    diskCacheGb = 10;
    strategy = 'conservative';
  }

  // Pre-render recommendation
  const prerenderEnabled = (
    analysis.staticLayers > 5 ||
    analysis.heavyEffects.length > 0 ||
    analysis.precompCount > 3
  );

  // Build reasoning
  const reasoningParts: string[] = [];
  reasoningParts.push(`Strategy: ${strategy}`);
  reasoningParts.push(`RAM: ${ramPreviewMb}MB`);
  reasoningParts.push(`Disk: ${diskCacheGb}GB`);
  if (prerenderEnabled) {
    reasoningParts.push('Pre-render recommended');
  }

  // Estimate speedup from good cache settings
  let speedup = 1.0;
  if (strategy === 'aggressive') speedup = 1.5;
  else if (strategy === 'balanced') speedup = 1.3;
  else speedup = 1.1;

  return {
    strategy,
    ramPreviewMb,
    diskCacheGb,
    prerenderEnabled,
    reasoning: reasoningParts.join(' | '),
    estimatedSpeedup: speedup
  };
}

/**
 * Create execution options for display
 */
export function createExecutionOptions(
  localEstimate: LocalEstimate,
  cloudEstimate?: { totalSeconds: number; costUsd: number; gpuClass: string },
  mode: ExecutionMode = 'smart'
): ExecutionOption[] {
  const options: ExecutionOption[] = [];

  // Local option (always available)
  const localOption: ExecutionOption = {
    decision: 'local_optimized',
    label: 'Local Optimized',
    description: `Render on your machine in ~${localEstimate.totalFormatted}`,
    estimatedSeconds: localEstimate.totalSeconds,
    estimatedCostUsd: 0,
    details: [
      `${localEstimate.frameCount} frames @ ${localEstimate.perFrameMs}ms each`,
      `Bottleneck: ${localEstimate.bottleneckDetail}`,
      `Optimizations: ${localEstimate.optimizations.join(', ') || 'Standard'}`
    ],
    pros: ['No cost', 'Your data stays local', 'Full control'],
    cons: localEstimate.totalSeconds > 1800 ? ['Long render time'] : [],
    isRecommended: mode === 'local_only' || !cloudEstimate,
    recommendationReason: mode === 'local_only'
      ? 'Local Only mode selected'
      : 'Local rendering is efficient',
    canExecute: true
  };

  if (localEstimate.speedupFactor >= 1.5) {
    localOption.pros.push(`${localEstimate.speedupFactor}x optimized`);
  }

  options.push(localOption);

  // Cloud option (if available and mode allows)
  if (cloudEstimate && mode !== 'local_only') {
    const timeSaved = localEstimate.totalSeconds - cloudEstimate.totalSeconds;
    const speedupVsLocal = localEstimate.totalSeconds / cloudEstimate.totalSeconds;

    const cloudOption: ExecutionOption = {
      decision: 'cloud_async',
      label: 'Cloud Render',
      description: `Render in cloud for $${cloudEstimate.costUsd.toFixed(2)}`,
      estimatedSeconds: cloudEstimate.totalSeconds,
      estimatedCostUsd: cloudEstimate.costUsd,
      details: [
        `~${formatDuration(cloudEstimate.totalSeconds)} on ${cloudEstimate.gpuClass.toUpperCase()}`,
        timeSaved > 60 ? `Saves ${formatDuration(timeSaved)} vs local` : ''
      ].filter(Boolean),
      pros: ['Faster completion', 'Frees your machine', 'Professional GPU'],
      cons: [`Costs $${cloudEstimate.costUsd.toFixed(2)}`, 'Requires upload'],
      isRecommended: mode === 'cloud_enabled' && speedupVsLocal > 2,
      recommendationReason: speedupVsLocal > 2
        ? `${Math.round(speedupVsLocal)}x faster than local`
        : 'Cloud available if needed',
      canExecute: true
    };

    options.push(cloudOption);
  }

  return options;
}

/**
 * Generate complete optimization analysis
 */
export function generateOptimizationAnalysis(
  manifest: Manifest,
  mode: ExecutionMode = 'smart',
  cloudEstimate?: { totalSeconds: number; costUsd: number; gpuClass: string }
): OptimizationAnalysis {
  // Perform composition analysis
  const analysis = manifest.analysis || analyzeComposition();

  // Calculate local estimate
  const localEstimate = calculateLocalEstimate(manifest, analysis);

  // Generate suggestions
  const suggestions = generateSuggestions(manifest, analysis);

  // Create execution options
  const executionOptions = createExecutionOptions(localEstimate, cloudEstimate, mode);

  // Determine recommended mode
  let recommendedMode: ExecutionMode = 'local_only';
  let reasoning = 'Local rendering is optimal for this composition';

  if (mode === 'local_only') {
    recommendedMode = 'local_only';
    reasoning = 'Local Only mode - all optimizations applied locally';
  } else if (cloudEstimate && localEstimate.totalSeconds > 3600) {
    // Long render - consider cloud
    const speedup = localEstimate.totalSeconds / cloudEstimate.totalSeconds;
    if (speedup > 3 && cloudEstimate.costUsd < 20) {
      recommendedMode = 'smart';
      reasoning = `Cloud could save ${formatDuration(localEstimate.totalSeconds - cloudEstimate.totalSeconds)}`;
    }
  }

  // Create headline
  let headline: string;
  if (mode === 'local_only') {
    headline = localEstimate.speedupFactor > 1.2
      ? `Local optimized: ~${localEstimate.totalFormatted} (${localEstimate.speedupFactor}x faster)`
      : `Local render: ~${localEstimate.totalFormatted}`;
  } else if (cloudEstimate) {
    headline = `Local ~${localEstimate.totalFormatted} | Cloud ~${formatDuration(cloudEstimate.totalSeconds)} ($${cloudEstimate.costUsd.toFixed(2)})`;
  } else {
    headline = `Local optimized: ~${localEstimate.totalFormatted}`;
  }

  // Create details
  const details: string[] = [
    `${localEstimate.frameCount} frames @ ${manifest.composition.fps} fps`,
    `Complexity: ${analysis.estimatedComplexity}/10`,
    localEstimate.bottleneckDetail
  ];

  if (localEstimate.optimizations.length > 0) {
    details.push(`Optimizations: ${localEstimate.optimizations.join(', ')}`);
  }

  if (suggestions.length > 0) {
    details.push(`Tip: ${suggestions[0].description}`);
  }

  // Hardware summary
  const caps = detectLocalCapabilities();
  const hardwareSummary = `${caps.estimatedCores} cores | ${caps.estimatedRamGb}GB RAM | GPU: ${caps.hasGpu ? 'Yes' : 'No'} | Tier: ${caps.tier}`;

  return {
    mode,
    recommendedMode,
    headline,
    reasoning,
    details,
    hardwareSummary,
    localEstimate,
    cloudEstimate: cloudEstimate ? {
      totalSeconds: cloudEstimate.totalSeconds,
      totalFormatted: formatDuration(cloudEstimate.totalSeconds),
      costUsd: cloudEstimate.costUsd,
      gpuClass: cloudEstimate.gpuClass,
      speedupVsLocal: Math.round((localEstimate.totalSeconds / cloudEstimate.totalSeconds) * 10) / 10
    } : undefined,
    suggestions,
    executionOptions
  };
}

/**
 * Quick analysis for fast UI updates
 */
export function quickAnalysis(manifest: Manifest): {
  complexity: number;
  estimatedMinutes: number;
  canOptimize: boolean;
} {
  const comp = manifest.composition;
  const frames = Math.round(comp.durationSeconds * comp.fps);
  const effects = manifest.effects.length;
  const expressions = manifest.expressionsCount;

  // Quick complexity
  let complexity = 1;
  complexity += Math.min(3, frames / 1000);
  complexity += Math.min(3, effects / 10);
  complexity += Math.min(3, expressions / 50);
  complexity = Math.min(10, Math.round(complexity));

  // Quick time estimate (50ms base per frame, adjusted)
  const msPerFrame = 50 * (1 + effects * 0.1 + expressions * 0.01);
  const estimatedMinutes = (frames * msPerFrame) / 60000;

  // Can optimize if there are opportunities
  const canOptimize = effects > 5 || expressions > 20 || frames > 500;

  return {
    complexity,
    estimatedMinutes: Math.round(estimatedMinutes),
    canOptimize
  };
}

/**
 * Get mode options for UI
 */
export function getModeOptions(): { value: ExecutionMode; label: string; description: string }[] {
  return [
    { value: 'local_only', ...MODE_LABELS.local_only },
    { value: 'smart', ...MODE_LABELS.smart },
    { value: 'cloud_enabled', ...MODE_LABELS.cloud_enabled }
  ];
}
