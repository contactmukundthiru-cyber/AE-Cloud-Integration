/**
 * Deep Composition Analysis and Collection
 *
 * This module provides comprehensive analysis of After Effects compositions
 * for local-first optimization. It extracts detailed information about:
 * - Layer structure and dependencies
 * - Effect complexity and GPU usage
 * - Expression patterns and bottlenecks
 * - Precomp nesting and parallelization opportunities
 *
 * "Make After Effects feel engineered, not mystical - even offline."
 */

import { CompositionAnalysis } from '../types';

export interface AssetRef {
  path: string;
  name: string;
}

export interface LayerInfo {
  index: number;
  name: string;
  type: string;
  inPoint: number;
  outPoint: number;
  isStatic: boolean;
  hasExpressions: boolean;
  expressionCount: number;
  effectCount: number;
  effectNames: string[];
  isPrecomp: boolean;
  parentIndex: number | null;
  isHidden: boolean;
  isLocked: boolean;
}

export interface EffectInfo {
  name: string;
  matchName: string;
  isHeavy: boolean;
  isGpuAccelerated: boolean;
  estimatedCostPerFrame: number; // milliseconds
}

// Heavy effects that significantly impact render time
const HEAVY_EFFECTS = [
  'ADBE Turbulent Displace',
  'ADBE Fractal Noise',
  'CC Particle World',
  'Particular',
  'Element',
  'ADBE Gaussian Blur 2',
  'ADBE Motion Blur',
  'ADBE Camera Lens Blur',
  'CC Radial Blur',
  'ADBE 3D Glasses2',
  'ADBE AE Warp Stabilizer',
  'ADBE Roto Brush 2',
  'Content-Aware Fill'
];

// GPU accelerated effects
const GPU_EFFECTS = [
  'ADBE Gaussian Blur 2',
  'ADBE Sharpen',
  'ADBE Lumetri',
  'ADBE HUE SATURATION',
  'ADBE Brightness & Contrast 2',
  'ADBE Exposure2',
  'ADBE Vibrance',
  'ADBE Pro Levels2',
  'ADBE CurvesCustom'
];

function getApp() {
  const app = (globalThis as any).app;
  if (!app || !app.project) {
    throw new Error('After Effects scripting API is not available.');
  }
  return app;
}

export function getActiveComp() {
  const app = getApp();
  const item = app.project.activeItem;
  if (!item || !item.duration || !item.numLayers) {
    throw new Error('No active composition selected.');
  }
  return item;
}

export function getProjectFilePath(): string {
  const app = getApp();
  if (!app.project.file) {
    throw new Error('Project must be saved before cloud export.');
  }
  return app.project.file.fsName || app.project.file.absoluteURI;
}

export function collectAssets(): AssetRef[] {
  const app = getApp();
  const assets: AssetRef[] = [];
  for (let i = 1; i <= app.project.numItems; i += 1) {
    const item = app.project.item(i);
    if (!item) {
      continue;
    }
    let file = null;
    if (item.mainSource && item.mainSource.file) {
      file = item.mainSource.file;
    } else if (item.file) {
      file = item.file;
    }
    if (file && file.exists) {
      const path = file.fsName || file.absoluteURI;
      assets.push({ path, name: file.name });
    }
  }
  return assets;
}

export function collectFonts(): string[] {
  const app = getApp();
  const fonts = new Set<string>();
  for (let i = 1; i <= app.project.numItems; i += 1) {
    const item = app.project.item(i);
    if (!item || !item.numLayers) {
      continue;
    }
    for (let l = 1; l <= item.numLayers; l += 1) {
      const layer = item.layer(l);
      if (!layer) {
        continue;
      }
      try {
        const textProp = layer.property('Source Text');
        if (textProp && textProp.value && textProp.value.font) {
          fonts.add(textProp.value.font);
        }
      } catch (err) {
        continue;
      }
    }
  }
  return Array.from(fonts).sort();
}

export function collectEffects(): string[] {
  const app = getApp();
  const effects = new Set<string>();
  for (let i = 1; i <= app.project.numItems; i += 1) {
    const item = app.project.item(i);
    if (!item || !item.numLayers) {
      continue;
    }
    for (let l = 1; l <= item.numLayers; l += 1) {
      const layer = item.layer(l);
      if (!layer) {
        continue;
      }
      const fx = layer.property('ADBE Effect Parade');
      if (!fx || !fx.numProperties) {
        continue;
      }
      for (let f = 1; f <= fx.numProperties; f += 1) {
        const effect = fx.property(f);
        if (effect && effect.matchName) {
          effects.add(effect.matchName);
        } else if (effect && effect.name) {
          effects.add(effect.name);
        }
      }
    }
  }
  return Array.from(effects).sort();
}

function countExpressionsInPropertyGroup(group: any): number {
  if (!group || !group.numProperties) {
    return 0;
  }
  let count = 0;
  for (let i = 1; i <= group.numProperties; i += 1) {
    const prop = group.property(i);
    if (!prop) {
      continue;
    }
    try {
      if (prop.canSetExpression && prop.expression && prop.expression !== '') {
        count += 1;
      }
    } catch (err) {
      // ignore
    }
    if (prop.numProperties && prop.numProperties > 0) {
      count += countExpressionsInPropertyGroup(prop);
    }
  }
  return count;
}

export function countExpressions(): number {
  const app = getApp();
  let total = 0;
  for (let i = 1; i <= app.project.numItems; i += 1) {
    const item = app.project.item(i);
    if (!item || !item.numLayers) {
      continue;
    }
    for (let l = 1; l <= item.numLayers; l += 1) {
      const layer = item.layer(l);
      if (!layer) {
        continue;
      }
      total += countExpressionsInPropertyGroup(layer);
    }
  }
  return total;
}

/**
 * Collect detailed information about all layers in a composition
 */
export function collectLayerInfo(comp?: any): LayerInfo[] {
  const targetComp = comp || getActiveComp();
  const layers: LayerInfo[] = [];

  for (let l = 1; l <= targetComp.numLayers; l += 1) {
    const layer = targetComp.layer(l);
    if (!layer) continue;

    const expressionCount = countExpressionsInPropertyGroup(layer);
    const effects = getLayerEffects(layer);

    // Determine layer type
    let layerType = 'unknown';
    try {
      if (layer.nullLayer) layerType = 'null';
      else if (layer.adjustmentLayer) layerType = 'adjustment';
      else if (layer.source && layer.source.numLayers) layerType = 'precomp';
      else if (layer.property('Source Text')) layerType = 'text';
      else if (layer.property('ADBE Vector Group')) layerType = 'shape';
      else if (layer.source) layerType = 'footage';
      else layerType = 'solid';
    } catch (e) {
      layerType = 'unknown';
    }

    // Check if layer is static (no keyframes, no expressions)
    const isStatic = checkLayerStatic(layer) && expressionCount === 0;

    // Get parent layer
    let parentIndex: number | null = null;
    try {
      if (layer.parent) {
        parentIndex = layer.parent.index;
      }
    } catch (e) {}

    layers.push({
      index: l,
      name: layer.name || `Layer ${l}`,
      type: layerType,
      inPoint: layer.inPoint || 0,
      outPoint: layer.outPoint || targetComp.duration,
      isStatic,
      hasExpressions: expressionCount > 0,
      expressionCount,
      effectCount: effects.length,
      effectNames: effects.map(e => e.name),
      isPrecomp: layerType === 'precomp',
      parentIndex,
      isHidden: !layer.enabled,
      isLocked: layer.locked || false
    });
  }

  return layers;
}

/**
 * Get effects from a layer with detailed info
 */
function getLayerEffects(layer: any): EffectInfo[] {
  const effects: EffectInfo[] = [];
  const fx = layer.property('ADBE Effect Parade');
  if (!fx || !fx.numProperties) return effects;

  for (let f = 1; f <= fx.numProperties; f += 1) {
    const effect = fx.property(f);
    if (!effect) continue;

    const matchName = effect.matchName || effect.name || 'Unknown';
    const name = effect.name || matchName;

    const isHeavy = HEAVY_EFFECTS.some(h =>
      matchName.toLowerCase().includes(h.toLowerCase()) ||
      name.toLowerCase().includes(h.toLowerCase())
    );

    const isGpuAccelerated = GPU_EFFECTS.some(g =>
      matchName.includes(g) || name.includes(g)
    );

    // Estimate cost per frame (rough heuristics)
    let costPerFrame = 5; // base 5ms
    if (isHeavy) costPerFrame = 50; // heavy effects
    else if (isGpuAccelerated) costPerFrame = 10; // GPU effects
    else costPerFrame = 15; // average effect

    effects.push({
      name,
      matchName,
      isHeavy,
      isGpuAccelerated,
      estimatedCostPerFrame: costPerFrame
    });
  }

  return effects;
}

/**
 * Check if a layer has no keyframes (is static)
 */
function checkLayerStatic(layer: any): boolean {
  try {
    // Check transform properties
    const transform = layer.property('ADBE Transform Group');
    if (transform) {
      for (let i = 1; i <= transform.numProperties; i++) {
        const prop = transform.property(i);
        if (prop && prop.numKeys && prop.numKeys > 0) {
          return false;
        }
      }
    }
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Count precomps and calculate nesting depth
 */
function analyzePrecompNesting(comp: any, depth: number = 0, visited: Set<string> = new Set()): { count: number; maxDepth: number } {
  let count = 0;
  let maxDepth = depth;

  const compId = comp.id || comp.name;
  if (visited.has(compId)) return { count, maxDepth };
  visited.add(compId);

  try {
    for (let l = 1; l <= comp.numLayers; l++) {
      const layer = comp.layer(l);
      if (!layer) continue;

      try {
        if (layer.source && layer.source.numLayers) {
          count += 1;
          const nested = analyzePrecompNesting(layer.source, depth + 1, visited);
          count += nested.count;
          maxDepth = Math.max(maxDepth, nested.maxDepth);
        }
      } catch (e) {}
    }
  } catch (e) {}

  return { count, maxDepth };
}

/**
 * Identify parallelizable layer groups
 * Layers that don't depend on each other can be rendered in parallel
 */
function findParallelizableGroups(layers: LayerInfo[]): number {
  // Group layers by time overlap and dependencies
  const groups: LayerInfo[][] = [];
  const used = new Set<number>();

  for (const layer of layers) {
    if (used.has(layer.index) || layer.isHidden) continue;
    if (layer.parentIndex !== null) continue; // Has parent dependency

    // Find other layers that don't overlap in time
    const group = [layer];
    used.add(layer.index);

    for (const other of layers) {
      if (used.has(other.index) || other.isHidden) continue;
      if (other.parentIndex !== null) continue;

      // Check if they don't overlap
      const overlaps = !(other.outPoint <= layer.inPoint || other.inPoint >= layer.outPoint);
      if (!overlaps) {
        group.push(other);
        used.add(other.index);
      }
    }

    if (group.length > 0) {
      groups.push(group);
    }
  }

  return groups.length;
}

/**
 * Perform deep composition analysis for optimization
 */
export function analyzeComposition(comp?: any): CompositionAnalysis {
  const targetComp = comp || getActiveComp();
  const layers = collectLayerInfo(targetComp);
  const effects = collectEffects();
  const expressionsTotal = countExpressions();

  // Analyze precomp structure
  const { count: precompCount, maxDepth: nestedDepth } = analyzePrecompNesting(targetComp);

  // Find heavy effects
  const heavyEffects = effects.filter(e =>
    HEAVY_EFFECTS.some(h => e.toLowerCase().includes(h.toLowerCase()))
  );

  // Count static and expression layers
  const staticLayers = layers.filter(l => l.isStatic && !l.isHidden).length;
  const expressionLayers = layers.filter(l => l.hasExpressions).length;

  // Find parallelizable groups
  const parallelizableGroups = findParallelizableGroups(layers);

  // Calculate complexity score (1-10)
  let complexity = 1;
  complexity += Math.min(3, layers.length / 20); // Layer count
  complexity += Math.min(2, effects.length / 10); // Effect count
  complexity += Math.min(2, expressionsTotal / 50); // Expression count
  complexity += Math.min(1, heavyEffects.length); // Heavy effects
  complexity += Math.min(1, nestedDepth / 3); // Nesting depth
  complexity = Math.min(10, Math.round(complexity));

  // Identify bottlenecks
  const bottlenecks: string[] = [];
  if (heavyEffects.length > 0) {
    bottlenecks.push(`${heavyEffects.length} heavy effect(s): ${heavyEffects.slice(0, 3).join(', ')}`);
  }
  if (expressionsTotal > 100) {
    bottlenecks.push(`High expression count (${expressionsTotal})`);
  }
  if (nestedDepth > 3) {
    bottlenecks.push(`Deep precomp nesting (${nestedDepth} levels)`);
  }
  if (layers.length > 50) {
    bottlenecks.push(`Many layers (${layers.length})`);
  }

  // Generate optimization hints
  const optimizationHints: string[] = [];

  if (staticLayers > 5) {
    optimizationHints.push(`${staticLayers} static layers can be pre-rendered`);
  }
  if (parallelizableGroups > 1) {
    optimizationHints.push(`${parallelizableGroups} layer groups can render in parallel`);
  }
  if (heavyEffects.length > 0 && GPU_EFFECTS.some(g => effects.includes(g))) {
    optimizationHints.push('GPU acceleration available for some effects');
  }
  if (expressionLayers > 0 && expressionLayers < layers.length / 2) {
    optimizationHints.push('Expression caching may improve performance');
  }
  if (precompCount > 3) {
    optimizationHints.push('Pre-render stable precomps for faster iteration');
  }

  return {
    layerCount: layers.length,
    precompCount,
    nestedDepth,
    heavyEffects,
    staticLayers,
    expressionLayers,
    parallelizableGroups,
    estimatedComplexity: complexity,
    bottlenecks,
    optimizationHints
  };
}

/**
 * Get a quick complexity score without full analysis
 */
export function getQuickComplexityScore(): number {
  const comp = getActiveComp();
  const layerCount = comp.numLayers || 0;
  const effectCount = collectEffects().length;
  const exprCount = countExpressions();

  let score = 1;
  score += Math.min(3, layerCount / 20);
  score += Math.min(3, effectCount / 10);
  score += Math.min(3, exprCount / 50);

  return Math.min(10, Math.round(score));
}

/**
 * Estimate render time per frame based on composition analysis
 */
export function estimatePerFrameTime(analysis?: CompositionAnalysis): number {
  const a = analysis || analyzeComposition();

  // Base time: 50ms per frame
  let msPerFrame = 50;

  // Add for effects
  msPerFrame += a.heavyEffects.length * 50;
  msPerFrame += (a.layerCount - a.heavyEffects.length) * 5;

  // Add for expressions
  msPerFrame += a.expressionLayers * 10;

  // Nesting overhead
  msPerFrame *= 1 + (a.nestedDepth * 0.1);

  return Math.round(msPerFrame);
}
