/**
 * CloudExport Plugin - Local-First After Effects Optimization
 *
 * This plugin embodies the local-first philosophy:
 * - Local-first optimization as the CORE differentiator
 * - Cloud is a capability, not a requirement
 * - Users always have agency over where work runs
 *
 * "Make After Effects feel engineered, not mystical - even offline."
 */

import './ui.css';
import { v4 as uuidv4 } from 'uuid';
import {
  createJob,
  estimateCost,
  getJobResult,
  getJobStatus,
  getUploadUrl,
  cancelJob
} from './api/client';
import {
  collectAssets,
  collectEffects,
  collectFonts,
  countExpressions,
  getActiveComp,
  getProjectFilePath,
  analyzeComposition
} from './ae/collector';
import {
  generateOptimizationAnalysis,
  quickAnalysis,
  getModeOptions,
  calculateLocalEstimate,
  getCacheRecommendation
} from './ae/localAnalysis';
import { getEntryFromPath, getFileMetadata, hashFile, readFileBytes, ensureOutputFolder, writeFileToFolder } from './utils/fs';
import { sha256Bytes, sha256String } from './utils/hash';
import { createBundleZip, stableStringify } from './utils/zip';
import { loadSettings, saveSettings } from './utils/settings';
import {
  Manifest,
  Preset,
  Settings,
  ExecutionMode,
  OptimizationAnalysis,
  LocalEstimate
} from './types';

interface BundleBuildResult {
  manifest: Manifest;
  entries: { path: string; data: Uint8Array }[];
  estimatedBundleSize: number;
}

interface AppState {
  settings: Settings | null;
  currentJobId: string;
  ws: WebSocket | null;
  pollingTimer: any;
  estimate: { costUsd: number; etaSeconds: number; gpuClass: string; warnings: string[] } | null;
  analysis: OptimizationAnalysis | null;
  localEstimate: LocalEstimate | null;
  executionMode: ExecutionMode;
  isAnalyzing: boolean;
}

const state: AppState = {
  settings: null,
  currentJobId: '',
  ws: null,
  pollingTimer: null,
  estimate: null,
  analysis: null,
  localEstimate: null,
  executionMode: 'smart',
  isAnalyzing: false
};

function $(id: string) {
  return document.getElementById(id) as HTMLInputElement;
}

function setStatus(text: string) {
  const el = $('status');
  if (el) {
    el.textContent = text;
  }
}

function setProgress(percent: number) {
  const el = $('progress');
  if (el) {
    el.textContent = `${Math.round(percent)}%`;
  }
  const bar = document.querySelector('.progress-bar span') as HTMLElement | null;
  if (bar) {
    bar.style.width = `${Math.min(100, Math.max(0, percent))}%`;
  }
}

function setError(message: string) {
  const el = $('error');
  el.textContent = message;
  el.style.display = 'block';
}

function clearError() {
  const el = $('error');
  el.textContent = '';
  el.style.display = 'none';
}

function updateAnalysisDisplay() {
  const analysisEl = $('analysis-content');
  const headlineEl = $('analysis-headline');
  const detailsEl = $('analysis-details');
  const suggestionsEl = $('suggestions-list');

  if (!state.analysis) {
    analysisEl.style.display = 'none';
    return;
  }

  analysisEl.style.display = 'block';
  const a = state.analysis;

  // Update headline
  headlineEl.textContent = a.headline;
  headlineEl.className = `headline ${a.recommendedMode === 'local_only' ? 'local' : a.recommendedMode === 'cloud_enabled' ? 'cloud' : 'smart'}`;

  // Update details
  detailsEl.innerHTML = a.details.map(d => `<div class="detail-item">${d}</div>`).join('');

  // Update suggestions
  if (a.suggestions.length > 0) {
    suggestionsEl.innerHTML = a.suggestions.slice(0, 3).map(s => `
      <div class="suggestion ${s.impact}">
        <span class="suggestion-title">${s.title}</span>
        <span class="suggestion-desc">${s.description}</span>
        ${s.automatic ? '<span class="auto-badge">Auto</span>' : ''}
      </div>
    `).join('');
    suggestionsEl.style.display = 'block';
  } else {
    suggestionsEl.style.display = 'none';
  }

  // Update execution options
  updateExecutionOptions();
}

function updateExecutionOptions() {
  const optionsEl = $('execution-options');
  if (!state.analysis) return;

  const options = state.analysis.executionOptions;
  optionsEl.innerHTML = options.map(opt => `
    <div class="exec-option ${opt.isRecommended ? 'recommended' : ''}" data-decision="${opt.decision}">
      <div class="option-header">
        <span class="option-label">${opt.label}</span>
        ${opt.isRecommended ? '<span class="rec-badge">Recommended</span>' : ''}
      </div>
      <div class="option-desc">${opt.description}</div>
      <div class="option-details">
        ${opt.estimatedCostUsd > 0 ? `<span class="cost">$${opt.estimatedCostUsd.toFixed(2)}</span>` : '<span class="cost free">Free</span>'}
      </div>
      ${opt.pros.length > 0 ? `<div class="option-pros">${opt.pros.slice(0, 2).join(' • ')}</div>` : ''}
    </div>
  `).join('');

  // Add click handlers
  optionsEl.querySelectorAll('.exec-option').forEach(el => {
    el.addEventListener('click', () => {
      optionsEl.querySelectorAll('.exec-option').forEach(o => o.classList.remove('selected'));
      el.classList.add('selected');
    });
  });
}

function updateEstimateDisplay() {
  if (!state.estimate && !state.localEstimate) return;

  const costEl = $('cost');
  const etaEl = $('eta');
  const gpuEl = $('gpu');
  const warningsEl = $('warnings');

  if (state.executionMode === 'local_only' && state.localEstimate) {
    costEl.textContent = 'Free';
    etaEl.textContent = state.localEstimate.totalFormatted;
    gpuEl.textContent = 'Local';
    warningsEl.textContent = state.localEstimate.bottleneckDetail || 'None';
  } else if (state.estimate) {
    costEl.textContent = `$${state.estimate.costUsd.toFixed(2)}`;
    etaEl.textContent = `${Math.max(1, Math.round(state.estimate.etaSeconds / 60))} min`;
    gpuEl.textContent = state.estimate.gpuClass;
    warningsEl.textContent = state.estimate.warnings?.join(' | ') || 'None';
  }
}

async function buildBundle(): Promise<BundleBuildResult> {
  const comp = getActiveComp();
  const projectPath = getProjectFilePath();
  const projectEntry = await getEntryFromPath(projectPath);
  const projectBytes = await readFileBytes(projectEntry);
  const projectMeta = await getFileMetadata(projectEntry);
  const projectHash = await sha256Bytes(projectBytes);

  const assets = collectAssets();
  const entries: { path: string; data: Uint8Array }[] = [];
  const manifestAssets = [] as Manifest['assets'];
  let totalSize = projectBytes.length;
  const seenPaths = new Set<string>();

  entries.push({ path: 'project.aep', data: projectBytes });

  for (const asset of assets) {
    if (seenPaths.has(asset.path)) {
      continue;
    }
    const entry = await getEntryFromPath(asset.path);
    const meta = await getFileMetadata(entry);
    const hash = await hashFile(entry);
    const bytes = await readFileBytes(entry);
    const assetId = uuidv4();
    const zipPath = `assets/${hash}/${asset.name}`;
    entries.push({ path: zipPath, data: bytes });
    manifestAssets.push({
      id: assetId,
      originalPath: asset.path,
      zipPath,
      sizeBytes: meta.size,
      sha256: hash,
      lastModified: meta.modified
    });
    seenPaths.add(asset.path);
    totalSize += bytes.length;
  }

  // Perform deep analysis
  const analysis = analyzeComposition();

  const manifest: Manifest = {
    schemaVersion: 1,
    project: {
      name: projectEntry.name,
      path: projectPath,
      hash: projectHash,
      sizeBytes: projectMeta.size,
      saved: true
    },
    composition: {
      name: comp.name,
      durationSeconds: comp.duration,
      fps: comp.frameRate,
      width: comp.width,
      height: comp.height,
      workAreaStart: comp.workAreaStart,
      workAreaDuration: comp.workAreaDuration
    },
    assets: manifestAssets,
    fonts: collectFonts(),
    effects: collectEffects(),
    expressionsCount: countExpressions(),
    createdAt: new Date().toISOString(),
    analysis
  };

  const manifestBytes = new TextEncoder().encode(JSON.stringify(manifest));
  totalSize += manifestBytes.length;

  return {
    manifest,
    entries,
    estimatedBundleSize: totalSize
  };
}

async function performAnalysis() {
  if (state.isAnalyzing) return;

  state.isAnalyzing = true;
  clearError();
  setStatus('Analyzing composition...');

  try {
    const bundle = await buildBundle();
    const preset = $('preset').value as Preset;

    // Always calculate local estimate first
    const localEstimate = calculateLocalEstimate(bundle.manifest, bundle.manifest.analysis);
    state.localEstimate = localEstimate;

    // Get cloud estimate if mode allows
    let cloudEstimate = null;
    if (state.executionMode !== 'local_only' && state.settings?.apiKey) {
      try {
        const customOptions = getCustomOptions();
        const estimate = await estimateCost(state.settings.apiBaseUrl, state.settings.apiKey, {
          manifest: bundle.manifest,
          preset,
          bundleSizeBytes: bundle.estimatedBundleSize,
          customOptions
        });
        state.estimate = estimate;
        cloudEstimate = {
          totalSeconds: estimate.etaSeconds,
          costUsd: estimate.costUsd,
          gpuClass: estimate.gpuClass
        };
      } catch (e) {
        // Cloud estimate failed, continue with local only
        console.log('Cloud estimate unavailable:', e);
      }
    }

    // Generate full analysis
    const analysis = generateOptimizationAnalysis(
      bundle.manifest,
      state.executionMode,
      cloudEstimate || undefined
    );
    state.analysis = analysis;

    // Update UI
    updateAnalysisDisplay();
    updateEstimateDisplay();
    setStatus('Analysis complete');

  } catch (err: any) {
    setError(err.message || 'Analysis failed');
    setStatus('Analysis failed');
  } finally {
    state.isAnalyzing = false;
  }
}

async function uploadBundle(bundle: BundleBuildResult, preset: Preset, allowCache: boolean) {
  const settings = state.settings as Settings;
  setStatus('Packaging bundle...');
  setProgress(5);

  const zipBytes = await createBundleZip(bundle.entries, bundle.manifest);
  const bundleHash = await sha256Bytes(zipBytes);
  const manifestHash = await sha256String(stableStringify(bundle.manifest));

  setStatus('Requesting upload URL...');
  setProgress(10);

  const upload = await getUploadUrl(settings.apiBaseUrl, settings.apiKey, {
    bundleSha256: bundleHash,
    bundleSizeBytes: zipBytes.length,
    projectHash: bundle.manifest.project.hash,
    manifestHash
  });

  setStatus('Uploading...');
  setProgress(20);

  const uploadHeaders = upload.headers || {};
  await fetch(upload.uploadUrl, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/zip',
      ...uploadHeaders
    },
    body: zipBytes
  });

  setStatus('Creating job...');
  setProgress(35);

  const customOptions = getCustomOptions();
  const response = await createJob(settings.apiBaseUrl, settings.apiKey, {
    bundleKey: upload.bundleKey,
    bundleSha256: bundleHash,
    bundleSizeBytes: zipBytes.length,
    manifestHash,
    manifest: bundle.manifest,
    preset,
    allowCache,
    outputName: `${bundle.manifest.composition.name}.${preset === 'high_quality' ? 'mov' : 'mp4'}`,
    notificationEmail: settings.notificationEmail,
    customOptions
  });

  state.currentJobId = response.jobId;
  setStatus(`Queued (${response.jobId})`);
  setProgress(40);

  const dashboardLink = document.getElementById('dashboard') as HTMLAnchorElement;
  dashboardLink.href = response.dashboardUrl;
  dashboardLink.style.display = 'inline';

  startMonitoring(response.wsUrl, response.jobId);
}

function getCustomOptions() {
  const preset = $('preset').value as Preset;
  if (preset !== 'custom') {
    return null;
  }
  return {
    width: parseInt($('custom-width').value, 10),
    height: parseInt($('custom-height').value, 10),
    fps: parseFloat($('custom-fps').value),
    bitrateMbps: parseFloat($('custom-bitrate').value),
    codec: $('custom-codec').value
  };
}

async function startExport() {
  clearError();

  // Check execution mode
  if (state.executionMode === 'local_only') {
    // Local render - just show the optimization info
    setStatus('Local render mode - use After Effects render queue with optimizations applied');
    showLocalRenderInstructions();
    return;
  }

  try {
    const settings = state.settings as Settings;
    if (!settings.apiKey) {
      throw new Error('API key required for cloud export. Use Local Only mode for local rendering.');
    }
    const bundle = await buildBundle();
    const preset = $('preset').value as Preset;
    await uploadBundle(bundle, preset, settings.allowCache);
  } catch (err: any) {
    setError(err.message || 'Export failed.');
    setStatus('Export failed');
  }
}

function showLocalRenderInstructions() {
  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>Local Render Optimizations</h2>
      <p>Your composition has been analyzed. Apply these optimizations for best performance:</p>
      <div class="optimization-list">
        ${state.analysis?.suggestions.map(s => `
          <div class="opt-item ${s.impact}">
            <strong>${s.title}</strong>
            <p>${s.description}</p>
          </div>
        `).join('') || '<p>No specific optimizations needed.</p>'}
      </div>
      <h3>Recommended Settings</h3>
      <ul>
        <li>Enable Multi-Frame Rendering in Preferences</li>
        <li>Set RAM Preview to at least 4GB</li>
        <li>Use Disk Cache (50GB+ recommended)</li>
        ${state.localEstimate?.optimizations.map(o => `<li>${o}</li>`).join('') || ''}
      </ul>
      <div class="modal-actions">
        <button class="primary" onclick="this.closest('.modal-overlay').remove()">Got it</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function downloadResult(jobId: string) {
  const settings = state.settings as Settings;
  const result = await getJobResult(settings.apiBaseUrl, settings.apiKey, jobId);
  setStatus('Downloading result...');
  const response = await fetch(result.downloadUrl);
  if (!response.ok) {
    throw new Error('Failed to download result.');
  }
  const arrayBuffer = await response.arrayBuffer();
  const outputFolder = await ensureOutputFolder(settings.outputDirUrl);
  await writeFileToFolder(outputFolder, result.filename, new Uint8Array(arrayBuffer));
  setStatus(`Saved to ${outputFolder.nativePath || outputFolder.name}`);
  setProgress(100);
}

function stopMonitoring() {
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
  if (state.pollingTimer) {
    clearInterval(state.pollingTimer);
    state.pollingTimer = null;
  }
}

function startMonitoring(wsUrl: string, jobId: string) {
  stopMonitoring();
  try {
    const { network } = require('uxp');
    const ws = new network.WebSocket(wsUrl);
    ws.onmessage = async (event: any) => {
      const data = JSON.parse(event.data);
      if (data.progressPercent !== undefined) {
        setProgress(data.progressPercent);
      }
      if (data.status) {
        setStatus(data.status);
      }
      if (data.status === 'COMPLETED') {
        stopMonitoring();
        await downloadResult(jobId);
      }
      if (data.status === 'FAILED' || data.status === 'CANCELLED') {
        stopMonitoring();
        setError(data.errorMessage || 'Render failed.');
      }
    };
    ws.onerror = () => {
      ws.close();
      startPolling(jobId);
    };
    state.ws = ws;
  } catch (err) {
    startPolling(jobId);
  }
}

function startPolling(jobId: string) {
  const settings = state.settings as Settings;
  state.pollingTimer = setInterval(async () => {
    try {
      const status = await getJobStatus(settings.apiBaseUrl, settings.apiKey, jobId);
      setProgress(status.progressPercent);
      setStatus(status.status);
      if (status.status === 'COMPLETED') {
        stopMonitoring();
        await downloadResult(jobId);
      }
      if (status.status === 'FAILED' || status.status === 'CANCELLED') {
        stopMonitoring();
        setError(status.errorMessage || 'Render failed.');
      }
    } catch (err) {
      // keep polling
    }
  }, 4000);
}

async function handleCancel() {
  const settings = state.settings as Settings;
  if (!state.currentJobId) {
    return;
  }
  await cancelJob(settings.apiBaseUrl, settings.apiKey, state.currentJobId);
  setStatus('Cancellation requested');
}

function toggleCustomOptions() {
  const preset = $('preset').value;
  const custom = document.getElementById('custom-options') as HTMLElement;
  custom.style.display = preset === 'custom' ? 'block' : 'none';
}

function handleModeChange() {
  const mode = $('execution-mode').value as ExecutionMode;
  state.executionMode = mode;

  // Update UI based on mode
  const cloudSection = document.querySelector('.cloud-section') as HTMLElement;
  const exportBtn = $('export-btn');

  if (mode === 'local_only') {
    cloudSection.style.opacity = '0.5';
    exportBtn.textContent = 'Show Local Optimizations';
  } else {
    cloudSection.style.opacity = '1';
    exportBtn.textContent = mode === 'cloud_enabled' ? 'Export to Cloud' : 'Smart Export';
  }

  // Re-run analysis with new mode
  if (state.analysis) {
    performAnalysis();
  }
}

async function init() {
  const settings = await loadSettings();
  // Apply defaults for new settings
  state.settings = {
    ...settings,
    executionMode: settings.executionMode || 'smart',
    localRenderEnabled: settings.localRenderEnabled ?? true,
    maxCloudCostPerJob: settings.maxCloudCostPerJob || 50,
    enablePrerender: settings.enablePrerender ?? true,
    cacheStrategy: settings.cacheStrategy || 'balanced'
  };
  state.executionMode = state.settings.executionMode;

  $('api-base').value = state.settings.apiBaseUrl;
  $('api-key').value = state.settings.apiKey;
  $('output-dir').value = state.settings.outputDirUrl;
  $('email').value = state.settings.notificationEmail;
  $('allow-cache').checked = state.settings.allowCache;
  $('execution-mode').value = state.executionMode;

  // Event listeners
  $('preset').addEventListener('change', toggleCustomOptions);
  $('execution-mode').addEventListener('change', handleModeChange);
  $('analyze-btn').addEventListener('click', performAnalysis);
  $('export-btn').addEventListener('click', startExport);
  $('cancel-btn').addEventListener('click', handleCancel);

  $('save-settings').addEventListener('click', async () => {
    const updated: Settings = {
      apiBaseUrl: $('api-base').value.trim(),
      apiKey: $('api-key').value.trim(),
      outputDirUrl: $('output-dir').value.trim(),
      notificationEmail: $('email').value.trim(),
      allowCache: $('allow-cache').checked,
      executionMode: $('execution-mode').value as ExecutionMode,
      localRenderEnabled: true,
      maxCloudCostPerJob: 50,
      enablePrerender: true,
      cacheStrategy: 'balanced'
    };
    state.settings = updated;
    await saveSettings(updated);
    setStatus('Settings saved');
  });

  $('choose-dir').addEventListener('click', async () => {
    const { storage } = require('uxp');
    const folder = await storage.localFileSystem.getFolder();
    if (folder) {
      $('output-dir').value = folder.url || folder.nativePath || folder.name;
    }
  });

  toggleCustomOptions();
  handleModeChange();
  setStatus('Ready - Click Analyze to start');
}

function renderUI() {
  if (document.getElementById('status')) {
    return;
  }

  const modeOptions = getModeOptions();

  document.body.innerHTML = `
    <div class="container">
      <h1>CloudExport</h1>
      <p class="subtitle">Local-first optimization with optional cloud</p>

      <!-- Execution Mode Selector -->
      <div class="section mode-section">
        <label>Execution Mode</label>
        <select id="execution-mode" class="mode-select">
          ${modeOptions.map(m => `
            <option value="${m.value}" ${m.value === 'smart' ? 'selected' : ''}>
              ${m.label}
            </option>
          `).join('')}
        </select>
        <div class="mode-description" id="mode-desc">
          System recommends optimal execution. You decide.
        </div>
      </div>

      <!-- Analysis Section -->
      <div class="section analysis-section">
        <button id="analyze-btn" class="analyze-button">Analyze Composition</button>
        <div id="analysis-content" style="display: none;">
          <div id="analysis-headline" class="headline"></div>
          <div id="analysis-details" class="details"></div>
          <div id="execution-options" class="execution-options"></div>
        </div>
      </div>

      <!-- Suggestions -->
      <div id="suggestions-list" class="suggestions" style="display: none;"></div>

      <!-- Preset -->
      <div class="section">
        <label>Output Preset</label>
        <select id="preset">
          <option value="web">Web (1080p H.264)</option>
          <option value="social">Social (1080p High Bitrate)</option>
          <option value="high_quality">High Quality (4K ProRes)</option>
          <option value="custom">Custom</option>
        </select>
      </div>

      <div id="custom-options" class="section" style="display: none;">
        <label>Custom Settings</label>
        <div class="grid">
          <input id="custom-width" type="number" value="1920" placeholder="Width" />
          <input id="custom-height" type="number" value="1080" placeholder="Height" />
          <input id="custom-fps" type="number" step="0.01" value="30" placeholder="FPS" />
          <input id="custom-bitrate" type="number" step="0.1" value="8" placeholder="Bitrate Mbps" />
          <select id="custom-codec">
            <option value="h264">H.264</option>
            <option value="prores">ProRes 422</option>
          </select>
        </div>
      </div>

      <!-- Estimate Display -->
      <div class="section cloud-section">
        <div class="info-grid">
          <div class="info-item">
            <span class="info-label">Cost</span>
            <span id="cost" class="info-value">--</span>
          </div>
          <div class="info-item">
            <span class="info-label">ETA</span>
            <span id="eta" class="info-value">--</span>
          </div>
          <div class="info-item">
            <span class="info-label">GPU</span>
            <span id="gpu" class="info-value">--</span>
          </div>
        </div>
        <div class="warnings">
          <span class="info-label">Notes:</span>
          <span id="warnings">None</span>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="section actions">
        <button id="export-btn" class="primary">Smart Export</button>
        <button id="cancel-btn" class="secondary">Cancel</button>
      </div>

      <!-- Progress -->
      <div class="section progress-section">
        <div class="status-line">
          <span>Status:</span>
          <span id="status">Ready</span>
        </div>
        <div class="progress-bar"><span></span></div>
        <div class="progress-value"><span id="progress">0%</span></div>
      </div>

      <div id="error" class="error"></div>

      <!-- Settings (Collapsible) -->
      <details class="settings-panel">
        <summary>Settings</summary>
        <div class="settings-content">
          <label>API Base URL</label>
          <input id="api-base" type="text" placeholder="https://api.cloudexport.io" />

          <label>API Key</label>
          <input id="api-key" type="password" placeholder="Your API key" />

          <label>Output Directory</label>
          <div class="row">
            <input id="output-dir" type="text" placeholder="Select output folder" />
            <button id="choose-dir">Choose</button>
          </div>

          <label>Notification Email</label>
          <input id="email" type="email" placeholder="email@example.com" />

          <label class="checkbox-row">
            <input id="allow-cache" type="checkbox" checked />
            <span>Enable smart caching</span>
          </label>

          <button id="save-settings" class="save-button">Save Settings</button>
        </div>
      </details>

      <a id="dashboard" class="dashboard-link" target="_blank" style="display:none;">Open Dashboard</a>

      <div class="footer">
        Local-first optimization • Cloud is optional
      </div>
    </div>
  `;

  // Add mode description updates
  const modeSelect = $('execution-mode');
  const modeDesc = $('mode-desc');
  modeSelect.addEventListener('change', () => {
    const mode = modeSelect.value;
    const opt = modeOptions.find(m => m.value === mode);
    if (opt && modeDesc) {
      modeDesc.textContent = opt.description;
    }
  });

  init();
}

const { entrypoints } = require('uxp');
entrypoints.setup({
  panels: {
    'cloudexport.panel': {
      show() {
        renderUI();
      }
    }
  }
});
