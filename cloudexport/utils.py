import hashlib
import json
from datetime import datetime


def canonical_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(',', ':'))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def hash_manifest(manifest: dict) -> str:
    return sha256_text(canonical_json(manifest))


def current_month() -> str:
    return datetime.utcnow().strftime('%Y-%m')
