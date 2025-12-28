from __future__ import annotations
from typing import Tuple, List
from .config import settings
from .compatibility import classify_effects


PRESET_BITRATES = {
    'web': 8.0,
    'social': 12.0,
    'high_quality': 200.0
}


def estimate_output_size_gb(duration_seconds: float, preset: str, custom_options: dict | None) -> float:
    bitrate_mbps = PRESET_BITRATES.get(preset, 8.0)
    if preset == 'custom' and custom_options:
        bitrate_mbps = float(custom_options.get('bitrateMbps', bitrate_mbps))
    bits = bitrate_mbps * 1_000_000 * duration_seconds
    bytes_out = bits / 8.0
    return bytes_out / (1024 ** 3)


def compute_complexity(manifest: dict) -> float:
    effects = manifest.get('effects', [])
    _, third_party = classify_effects(effects)
    complexity = 1.0
    if len(effects) > 10:
        complexity += 0.5
    if len(effects) > 30:
        complexity += 1.0
    if third_party:
        complexity += 0.5
    expressions = manifest.get('expressionsCount', 0)
    if expressions > 50:
        complexity += 0.5
    if expressions > 150:
        complexity += 0.5
    return complexity


def choose_gpu_class(manifest: dict, preset: str) -> str:
    comp = manifest['composition']
    duration = comp['durationSeconds']
    complexity = compute_complexity(manifest)
    if duration > 600 or complexity >= 2.5 or preset == 'high_quality':
        return 'a100'
    return 'rtx4090'


def estimate_cost(manifest: dict, preset: str, bundle_size_bytes: int, custom_options: dict | None = None) -> Tuple[float, int, str, List[str]]:
    warnings: List[str] = []
    gpu_class = choose_gpu_class(manifest, preset)
    complexity = compute_complexity(manifest)
    duration_seconds = manifest['composition']['durationSeconds']
    speed_factor = settings.gpu_speed_factor.get(gpu_class, 1.0)
    render_minutes = (duration_seconds / 60.0) * (complexity / speed_factor)
    rate = settings.gpu_rate_per_minute.get(gpu_class, 1.0)

    output_gb = estimate_output_size_gb(duration_seconds, preset, custom_options)
    bundle_gb = bundle_size_bytes / (1024 ** 3)
    storage_hours = max(1.0, render_minutes / 60.0)
    storage_cost = (bundle_gb + output_gb) * settings.storage_rate_per_gb_hour * storage_hours
    transfer_cost = output_gb * settings.transfer_rate_per_gb

    render_cost = render_minutes * rate
    total = max(settings.min_job_cost_usd, render_cost + storage_cost + transfer_cost)

    upload_seconds = (bundle_size_bytes * 8) / (settings.upload_mbps * 1_000_000)
    eta_seconds = int(render_minutes * 60 + upload_seconds + 120)

    if bundle_gb > 5:
        warnings.append('Large bundle; upload may take longer.')
    if complexity >= 2.5:
        warnings.append('Complex composition; expect longer render time.')

    return round(total, 2), eta_seconds, gpu_class, warnings


def compute_actual_cost(
    manifest: dict,
    preset: str,
    bundle_size_bytes: int,
    render_minutes: float,
    custom_options: dict | None = None
) -> float:
    gpu_class = choose_gpu_class(manifest, preset)
    rate = settings.gpu_rate_per_minute.get(gpu_class, 1.0)
    render_cost = render_minutes * rate

    duration_seconds = manifest['composition']['durationSeconds']
    output_gb = estimate_output_size_gb(duration_seconds, preset, custom_options)
    bundle_gb = bundle_size_bytes / (1024 ** 3)
    storage_hours = max(1.0, render_minutes / 60.0)
    storage_cost = (bundle_gb + output_gb) * settings.storage_rate_per_gb_hour * storage_hours
    transfer_cost = output_gb * settings.transfer_rate_per_gb

    total = max(settings.min_job_cost_usd, render_cost + storage_cost + transfer_cost)
    return round(total, 2)
