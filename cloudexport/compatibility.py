from typing import List, Tuple

BLOCKED_EFFECT_PREFIXES = {
    'Sapphire',
    'Boris',
    'RedGiant',
    'VideoCopilot',
    'Element3D',
    'Trapcode'
}

BLOCKED_EFFECTS = {
    'VC Element',
    'Trapcode Particular'
}


def classify_effects(effects: List[str]) -> Tuple[List[str], List[str]]:
    native = []
    third_party = []
    for effect in effects:
        if effect.startswith('ADBE'):
            native.append(effect)
            continue
        if effect in BLOCKED_EFFECTS:
            third_party.append(effect)
            continue
        if any(effect.startswith(prefix) for prefix in BLOCKED_EFFECT_PREFIXES):
            third_party.append(effect)
            continue
        if effect.startswith('PG') or effect.startswith('CC'):
            native.append(effect)
            continue
        third_party.append(effect)
    return native, third_party


def check_manifest(manifest: dict) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    effects = manifest.get('effects', [])
    _, third_party = classify_effects(effects)
    if third_party:
        warnings.append(f'Third-party effects detected: {", ".join(sorted(set(third_party)))}')
    fonts = manifest.get('fonts', [])
    if not fonts:
        warnings.append('No fonts detected; verify text layers use default fonts.')
    if manifest.get('expressionsCount', 0) > 100:
        warnings.append('High expression count may slow render.')
    return warnings, errors
