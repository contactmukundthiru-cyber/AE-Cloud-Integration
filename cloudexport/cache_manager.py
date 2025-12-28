"""
Advanced Cache Strategy Manager

Implements sophisticated caching strategies for local-first optimization:
- Adaptive RAM preview limits
- Disk cache optimization
- Predictive cache warming
- Frame-level caching
- Invalidation logic

"The system's intelligence is measured by how much it can extract
from local hardware before ever suggesting cloud."
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple, Any
from enum import Enum
from pathlib import Path
import hashlib
import json
import time
import os
import shutil


class CacheType(Enum):
    """Types of cache storage."""
    RAM_PREVIEW = "ram_preview"       # AE's built-in RAM preview
    DISK_CACHE = "disk_cache"         # AE's disk cache
    PRERENDER = "prerender"           # Pre-rendered sequences
    EXPRESSION = "expression"          # Cached expression results
    THUMBNAIL = "thumbnail"            # UI thumbnails
    ANALYSIS = "analysis"              # Optimization analysis cache


class CacheStrategy(Enum):
    """Caching strategy modes."""
    CONSERVATIVE = "conservative"      # Minimize disk usage
    BALANCED = "balanced"              # Balance speed and storage
    AGGRESSIVE = "aggressive"          # Maximize speed, use more storage
    ADAPTIVE = "adaptive"              # Dynamically adjust based on usage


class CachePriority(Enum):
    """Priority for cache entries."""
    CRITICAL = 4    # Must keep (active project)
    HIGH = 3        # Should keep (recent/frequent)
    MEDIUM = 2      # Could keep (if space allows)
    LOW = 1         # Can evict (old/infrequent)


@dataclass
class CacheEntry:
    """Represents a cached item."""
    key: str
    cache_type: CacheType
    priority: CachePriority

    # Storage info
    path: Optional[str] = None
    size_bytes: int = 0
    in_memory: bool = False

    # Timing
    created_at: float = 0.0
    last_accessed: float = 0.0
    access_count: int = 0
    ttl_seconds: Optional[float] = None  # Time-to-live

    # Content info
    manifest_hash: Optional[str] = None
    frame_range: Optional[Tuple[int, int]] = None
    format: str = "unknown"

    # Validity
    is_valid: bool = True
    invalidation_reason: Optional[str] = None

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at

    @property
    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return self.age_seconds > self.ttl_seconds

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


@dataclass
class CacheBudget:
    """Cache storage budget."""
    ram_mb: int = 4096
    disk_gb: float = 50.0
    max_age_hours: float = 168.0  # 7 days

    # Dynamic limits
    current_ram_mb: int = 0
    current_disk_gb: float = 0.0


@dataclass
class CacheStats:
    """Cache usage statistics."""
    total_entries: int = 0
    total_size_bytes: int = 0
    ram_entries: int = 0
    disk_entries: int = 0

    hits: int = 0
    misses: int = 0

    # By type
    by_type: Dict[str, int] = field(default_factory=dict)
    by_priority: Dict[str, int] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


@dataclass
class CacheRecommendation:
    """Recommendation for cache settings."""
    strategy: CacheStrategy
    ram_preview_mb: int
    disk_cache_gb: float
    prerender_enabled: bool

    reasoning: str
    estimated_speedup: float

    # Specific settings
    ae_cache_settings: Dict[str, Any] = field(default_factory=dict)


class CacheManager:
    """
    Manages all caching for local-first optimization.

    Responsibilities:
    - Track all cache entries
    - Enforce storage budgets
    - Implement eviction policies
    - Provide cache warming
    - Handle invalidation
    """

    def __init__(self, cache_dir: Path, budget: Optional[CacheBudget] = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.budget = budget or CacheBudget()
        self.entries: Dict[str, CacheEntry] = {}
        self.stats = CacheStats()
        self.strategy = CacheStrategy.BALANCED

        # Load existing cache index
        self._load_index()

    def _load_index(self) -> None:
        """Load cache index from disk."""
        index_path = self.cache_dir / "cache_index.json"
        if index_path.exists():
            try:
                with open(index_path, "r") as f:
                    data = json.load(f)
                for key, entry_data in data.get("entries", {}).items():
                    self.entries[key] = CacheEntry(
                        key=key,
                        cache_type=CacheType(entry_data.get("type", "disk_cache")),
                        priority=CachePriority(entry_data.get("priority", 2)),
                        path=entry_data.get("path"),
                        size_bytes=entry_data.get("size_bytes", 0),
                        created_at=entry_data.get("created_at", time.time()),
                        last_accessed=entry_data.get("last_accessed", time.time()),
                        access_count=entry_data.get("access_count", 0),
                        manifest_hash=entry_data.get("manifest_hash"),
                        format=entry_data.get("format", "unknown")
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    def _save_index(self) -> None:
        """Save cache index to disk."""
        index_path = self.cache_dir / "cache_index.json"
        data = {
            "entries": {
                key: {
                    "type": entry.cache_type.value,
                    "priority": entry.priority.value,
                    "path": entry.path,
                    "size_bytes": entry.size_bytes,
                    "created_at": entry.created_at,
                    "last_accessed": entry.last_accessed,
                    "access_count": entry.access_count,
                    "manifest_hash": entry.manifest_hash,
                    "format": entry.format
                }
                for key, entry in self.entries.items()
            },
            "updated_at": time.time()
        }
        with open(index_path, "w") as f:
            json.dump(data, f, indent=2)

    def compute_key(self, manifest: dict, cache_type: CacheType, suffix: str = "") -> str:
        """Compute cache key from manifest."""
        key_data = json.dumps({
            "composition": manifest.get("composition", {}),
            "effects": manifest.get("effects", []),
            "expressionsCount": manifest.get("expressionsCount", 0),
            "type": cache_type.value,
            "suffix": suffix
        }, sort_keys=True)
        return hashlib.sha256(key_data.encode()).hexdigest()[:24]

    def get(self, key: str) -> Optional[CacheEntry]:
        """Get a cache entry, updating access stats."""
        entry = self.entries.get(key)
        if entry:
            if entry.is_expired or not entry.is_valid:
                self.stats.misses += 1
                return None

            entry.last_accessed = time.time()
            entry.access_count += 1
            self.stats.hits += 1
            return entry

        self.stats.misses += 1
        return None

    def put(
        self,
        key: str,
        cache_type: CacheType,
        path: str,
        size_bytes: int,
        priority: CachePriority = CachePriority.MEDIUM,
        manifest_hash: Optional[str] = None,
        ttl_seconds: Optional[float] = None
    ) -> CacheEntry:
        """Add or update a cache entry."""
        # Enforce budget before adding
        self._enforce_budget(size_bytes)

        entry = CacheEntry(
            key=key,
            cache_type=cache_type,
            priority=priority,
            path=path,
            size_bytes=size_bytes,
            created_at=time.time(),
            last_accessed=time.time(),
            access_count=1,
            manifest_hash=manifest_hash,
            ttl_seconds=ttl_seconds
        )

        self.entries[key] = entry
        self._update_stats()
        self._save_index()

        return entry

    def invalidate(self, key: str, reason: str = "manual") -> bool:
        """Invalidate a cache entry."""
        if key in self.entries:
            entry = self.entries[key]
            entry.is_valid = False
            entry.invalidation_reason = reason
            return True
        return False

    def invalidate_by_manifest(self, manifest_hash: str, reason: str = "manifest_changed") -> int:
        """Invalidate all entries for a manifest."""
        count = 0
        for entry in self.entries.values():
            if entry.manifest_hash == manifest_hash:
                entry.is_valid = False
                entry.invalidation_reason = reason
                count += 1
        return count

    def evict(self, key: str) -> bool:
        """Remove a cache entry and its data."""
        if key not in self.entries:
            return False

        entry = self.entries[key]

        # Delete file if exists
        if entry.path and os.path.exists(entry.path):
            try:
                if os.path.isdir(entry.path):
                    shutil.rmtree(entry.path)
                else:
                    os.remove(entry.path)
            except OSError:
                pass

        del self.entries[key]
        self._update_stats()
        self._save_index()
        return True

    def _enforce_budget(self, new_size_bytes: int) -> None:
        """Enforce storage budget by evicting entries if needed."""
        current_size = sum(e.size_bytes for e in self.entries.values())
        budget_bytes = self.budget.disk_gb * 1024 * 1024 * 1024

        if current_size + new_size_bytes <= budget_bytes:
            return

        # Need to evict
        # Sort by priority (low first), then by last accessed (oldest first)
        evict_candidates = sorted(
            [e for e in self.entries.values() if e.is_valid],
            key=lambda e: (e.priority.value, e.last_accessed)
        )

        freed = 0
        needed = new_size_bytes - (budget_bytes - current_size)

        for entry in evict_candidates:
            if freed >= needed:
                break
            if entry.priority != CachePriority.CRITICAL:
                freed += entry.size_bytes
                self.evict(entry.key)

    def _update_stats(self) -> None:
        """Update cache statistics."""
        self.stats.total_entries = len(self.entries)
        self.stats.total_size_bytes = sum(e.size_bytes for e in self.entries.values())
        self.stats.ram_entries = sum(1 for e in self.entries.values() if e.in_memory)
        self.stats.disk_entries = sum(1 for e in self.entries.values() if not e.in_memory)

        # By type
        self.stats.by_type = {}
        for entry in self.entries.values():
            t = entry.cache_type.value
            self.stats.by_type[t] = self.stats.by_type.get(t, 0) + 1

        # By priority
        self.stats.by_priority = {}
        for entry in self.entries.values():
            p = entry.priority.name
            self.stats.by_priority[p] = self.stats.by_priority.get(p, 0) + 1

    def cleanup_expired(self) -> int:
        """Remove all expired entries."""
        expired = [k for k, e in self.entries.items() if e.is_expired]
        for key in expired:
            self.evict(key)
        return len(expired)

    def cleanup_invalid(self) -> int:
        """Remove all invalid entries."""
        invalid = [k for k, e in self.entries.items() if not e.is_valid]
        for key in invalid:
            self.evict(key)
        return len(invalid)

    def get_stats(self) -> dict:
        """Get cache statistics as dict."""
        self._update_stats()
        return {
            "total_entries": self.stats.total_entries,
            "total_size_mb": self.stats.total_size_bytes / (1024 * 1024),
            "ram_entries": self.stats.ram_entries,
            "disk_entries": self.stats.disk_entries,
            "hit_rate": round(self.stats.hit_rate * 100, 1),
            "hits": self.stats.hits,
            "misses": self.stats.misses,
            "by_type": self.stats.by_type,
            "by_priority": self.stats.by_priority
        }


class CacheAdvisor:
    """
    Provides intelligent cache recommendations.

    Analyzes:
    - Available system resources
    - Composition characteristics
    - Historical usage patterns
    - Current cache state
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager

    def recommend_settings(
        self,
        manifest: dict,
        available_ram_mb: int,
        available_disk_gb: float,
        usage_pattern: str = "mixed"  # "interactive", "batch", "mixed"
    ) -> CacheRecommendation:
        """Generate cache settings recommendation."""
        comp = manifest.get('composition', {})
        duration = comp.get('durationSeconds', 0)
        fps = comp.get('fps', 30)
        width = comp.get('width', 1920)
        height = comp.get('height', 1080)
        frames = int(duration * fps)

        effects = len(manifest.get('effects', []))
        expressions = manifest.get('expressionsCount', 0)

        # Calculate frame size
        bytes_per_pixel = 16  # 32-bit RGBA (AE internal)
        frame_bytes = width * height * bytes_per_pixel
        frame_mb = frame_bytes / (1024 * 1024)

        # Determine strategy
        if usage_pattern == "interactive":
            strategy = CacheStrategy.AGGRESSIVE
            speedup = 1.5
        elif usage_pattern == "batch":
            strategy = CacheStrategy.CONSERVATIVE
            speedup = 1.1
        else:
            strategy = CacheStrategy.BALANCED
            speedup = 1.3

        # RAM preview calculation
        # Aim to cache at least 2 seconds of preview
        min_preview_frames = int(fps * 2)
        ideal_preview_mb = min_preview_frames * frame_mb

        # Don't use more than 60% of available RAM for preview
        max_preview_mb = int(available_ram_mb * 0.6)
        ram_preview_mb = min(max_preview_mb, max(2048, int(ideal_preview_mb)))

        # Disk cache calculation
        # Base: 10GB, scale with composition complexity
        base_disk = 10.0
        if effects > 10 or expressions > 50:
            base_disk = 25.0
        if duration > 300:  # 5+ minutes
            base_disk = 50.0

        # Cap at 80% of available disk
        disk_cache_gb = min(available_disk_gb * 0.8, base_disk)

        # Pre-render recommendation
        prerender_enabled = (
            effects > 5 or
            expressions > 20 or
            duration > 60
        )

        reasoning = self._build_reasoning(
            strategy, ram_preview_mb, disk_cache_gb,
            prerender_enabled, effects, expressions, duration
        )

        # AE-specific settings
        ae_settings = {
            "ramPreviewMB": ram_preview_mb,
            "diskCacheGB": disk_cache_gb,
            "diskCacheEnabled": True,
            "conformed_media_cache": True,
            "purge_preview_on_timeline_change": False if strategy == CacheStrategy.AGGRESSIVE else True,
            "auto_purge_memory_at": 0.85  # Purge at 85% memory usage
        }

        return CacheRecommendation(
            strategy=strategy,
            ram_preview_mb=ram_preview_mb,
            disk_cache_gb=disk_cache_gb,
            prerender_enabled=prerender_enabled,
            reasoning=reasoning,
            estimated_speedup=speedup,
            ae_cache_settings=ae_settings
        )

    def _build_reasoning(
        self,
        strategy: CacheStrategy,
        ram_mb: int,
        disk_gb: float,
        prerender: bool,
        effects: int,
        expressions: int,
        duration: float
    ) -> str:
        """Build human-readable reasoning."""
        parts = []

        parts.append(f"Strategy: {strategy.value.title()}")
        parts.append(f"RAM Preview: {ram_mb}MB allocated")
        parts.append(f"Disk Cache: {disk_gb:.1f}GB allocated")

        if prerender:
            reasons = []
            if effects > 5:
                reasons.append(f"{effects} effects")
            if expressions > 20:
                reasons.append(f"{expressions} expressions")
            if duration > 60:
                reasons.append(f"{duration:.0f}s duration")
            parts.append(f"Pre-render recommended ({', '.join(reasons)})")

        return " | ".join(parts)

    def get_warming_suggestions(self, manifest: dict) -> List[dict]:
        """Suggest what to pre-cache for faster workflow."""
        suggestions = []

        effects = manifest.get('effects', [])
        if len(effects) > 10:
            suggestions.append({
                "action": "prerender_effects",
                "description": "Pre-render effect-heavy layers",
                "estimated_time": len(effects) * 5,  # 5s per effect
                "priority": "high"
            })

        expressions = manifest.get('expressionsCount', 0)
        if expressions > 50:
            suggestions.append({
                "action": "cache_expressions",
                "description": "Enable expression caching",
                "estimated_time": 10,
                "priority": "high"
            })

        comp = manifest.get('composition', {})
        duration = comp.get('durationSeconds', 0)
        if duration > 60:
            suggestions.append({
                "action": "preview_cache",
                "description": "Build RAM preview for critical sections",
                "estimated_time": duration * 0.1,
                "priority": "medium"
            })

        return suggestions


def get_cache_recommendation(manifest: dict, system_caps: dict) -> dict:
    """
    High-level API: Get cache settings recommendation.

    Args:
        manifest: CloudExport manifest
        system_caps: System capabilities dict

    Returns:
        Cache recommendation dict
    """
    # Create temporary cache manager for analysis
    cache_dir = Path.home() / ".cloudexport" / "cache"
    manager = CacheManager(cache_dir)
    advisor = CacheAdvisor(manager)

    available_ram = system_caps.get("memory", {}).get("available_mb", 8192)
    available_disk = 100.0  # Default 100GB

    disks = system_caps.get("disks", [])
    if disks:
        available_disk = max(d.get("free_gb", 50) for d in disks)

    recommendation = advisor.recommend_settings(
        manifest,
        available_ram,
        available_disk
    )

    warming = advisor.get_warming_suggestions(manifest)

    return {
        "strategy": recommendation.strategy.value,
        "ram_preview_mb": recommendation.ram_preview_mb,
        "disk_cache_gb": recommendation.disk_cache_gb,
        "prerender_enabled": recommendation.prerender_enabled,
        "reasoning": recommendation.reasoning,
        "estimated_speedup": recommendation.estimated_speedup,
        "ae_settings": recommendation.ae_cache_settings,
        "warming_suggestions": warming,
        "current_stats": manager.get_stats()
    }
