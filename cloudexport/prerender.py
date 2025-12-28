"""
Intelligent Pre-Rendering System

Automatically identifies and pre-renders:
- Stable sub-compositions
- Repeated elements
- Expression-heavy layers
- Static backgrounds

This dramatically speeds up iterative workflows by caching expensive operations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from enum import Enum
from pathlib import Path
import hashlib
import json
import time


class PreRenderPriority(Enum):
    """Priority level for pre-render candidates."""
    CRITICAL = 4   # Must pre-render (blocking main render)
    HIGH = 3       # Should pre-render (significant savings)
    MEDIUM = 2     # Could pre-render (moderate savings)
    LOW = 1        # Optional pre-render (minor savings)


class PreRenderStatus(Enum):
    """Status of a pre-render task."""
    PENDING = "pending"
    QUEUED = "queued"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


@dataclass
class PreRenderCandidate:
    """A layer or composition that could benefit from pre-rendering."""
    id: str
    name: str
    layer_type: str  # "composition", "layer", "precomp"

    # Analysis results
    is_static: bool = False
    is_repeated: bool = False
    has_expressions: bool = False
    expression_count: int = 0
    effect_count: int = 0

    # Timing
    in_point: float = 0.0
    out_point: float = 0.0
    duration: float = 0.0
    frame_count: int = 0

    # Cost analysis
    estimated_render_time: float = 0.0
    times_used: int = 1  # How many times this appears in composition
    total_savings_if_cached: float = 0.0

    # Priority
    priority: PreRenderPriority = PreRenderPriority.LOW
    priority_score: float = 0.0

    # Dependencies
    depends_on: Set[str] = field(default_factory=set)
    required_by: Set[str] = field(default_factory=set)

    # Cache info
    cache_key: Optional[str] = None
    cache_size_estimate_mb: float = 0.0


@dataclass
class PreRenderTask:
    """A scheduled pre-render operation."""
    id: str
    candidate: PreRenderCandidate
    status: PreRenderStatus = PreRenderStatus.PENDING

    # Execution
    output_path: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    actual_render_time: float = 0.0

    # Result
    output_format: str = "png_sequence"  # or "exr_sequence", "prores"
    frame_count: int = 0
    total_size_bytes: int = 0
    cache_key: Optional[str] = None

    # Error handling
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2


@dataclass
class PreRenderPlan:
    """Complete pre-render execution plan."""
    tasks: List[PreRenderTask]
    execution_order: List[str]  # Task IDs in order
    total_estimated_time: float
    total_estimated_savings: float
    total_cache_size_mb: float

    # Status
    completed_tasks: int = 0
    failed_tasks: int = 0


class PreRenderAnalyzer:
    """
    Analyzes a composition to identify pre-render candidates.

    This is intelligent analysis that goes beyond simple static detection:
    - Tracks layer dependencies
    - Identifies expression patterns
    - Calculates cost/benefit for each candidate
    - Produces optimal pre-render order
    """

    def __init__(self, manifest: dict, fps: float = 30.0):
        self.manifest = manifest
        self.fps = fps
        self.candidates: Dict[str, PreRenderCandidate] = {}

    def analyze(self) -> List[PreRenderCandidate]:
        """Analyze manifest and return pre-render candidates."""
        # Extract composition info
        comp = self.manifest.get('composition', {})
        duration = comp.get('durationSeconds', 0)
        total_frames = int(duration * self.fps)

        # Analyze effects for static/dynamic patterns
        effects = self.manifest.get('effects', [])
        expr_count = self.manifest.get('expressionsCount', 0)
        assets = self.manifest.get('assets', [])

        # Create main composition candidate
        main_id = f"comp_{comp.get('name', 'main')}"
        main_candidate = PreRenderCandidate(
            id=main_id,
            name=comp.get('name', 'Main'),
            layer_type="composition",
            has_expressions=expr_count > 0,
            expression_count=expr_count,
            effect_count=len(effects),
            duration=duration,
            frame_count=total_frames,
            estimated_render_time=self._estimate_render_time(total_frames, len(effects), expr_count)
        )
        self.candidates[main_id] = main_candidate

        # Analyze assets (footage items)
        for asset in assets:
            asset_id = f"asset_{asset.get('id', '')}"
            is_static = self._is_static_asset(asset)

            candidate = PreRenderCandidate(
                id=asset_id,
                name=asset.get('zipPath', 'Unknown'),
                layer_type="asset",
                is_static=is_static,
                cache_size_estimate_mb=asset.get('sizeBytes', 0) / (1024 * 1024)
            )

            if is_static:
                candidate.priority = PreRenderPriority.LOW
                candidate.priority_score = 0.5

            self.candidates[asset_id] = candidate

        # Identify expression-heavy pseudo-layers
        if expr_count > 20:
            expr_id = "expressions_heavy"
            candidate = PreRenderCandidate(
                id=expr_id,
                name=f"Expression-Heavy Layers ({expr_count} expressions)",
                layer_type="expression_group",
                has_expressions=True,
                expression_count=expr_count,
                duration=duration,
                frame_count=total_frames,
                estimated_render_time=expr_count * 0.001 * total_frames,  # 1ms per expr per frame
                priority=PreRenderPriority.HIGH,
                priority_score=min(10, expr_count / 20)
            )
            candidate.total_savings_if_cached = candidate.estimated_render_time * 0.8
            self.candidates[expr_id] = candidate

        # Identify effect-heavy candidates
        heavy_effects = self._identify_heavy_effects(effects)
        if heavy_effects:
            for i, effect_name in enumerate(heavy_effects):
                effect_id = f"effect_heavy_{i}"
                candidate = PreRenderCandidate(
                    id=effect_id,
                    name=f"Heavy Effect: {effect_name}",
                    layer_type="effect",
                    effect_count=1,
                    duration=duration,
                    frame_count=total_frames,
                    estimated_render_time=0.1 * total_frames,  # 100ms per frame for heavy effect
                    priority=PreRenderPriority.MEDIUM,
                    priority_score=5.0
                )
                candidate.total_savings_if_cached = candidate.estimated_render_time * 0.9
                self.candidates[effect_id] = candidate

        # Calculate priorities and scores
        self._calculate_priorities()

        # Return sorted by priority
        return sorted(
            self.candidates.values(),
            key=lambda c: (c.priority.value, c.priority_score),
            reverse=True
        )

    def _is_static_asset(self, asset: dict) -> bool:
        """Determine if an asset is static (image vs video)."""
        path = asset.get('zipPath', '').lower()
        static_extensions = ['.png', '.jpg', '.jpeg', '.psd', '.ai', '.eps', '.tiff', '.tif']
        return any(path.endswith(ext) for ext in static_extensions)

    def _estimate_render_time(self, frames: int, effects: int, expressions: int) -> float:
        """Estimate render time in seconds."""
        base = frames * 0.05  # 50ms per frame baseline
        effect_time = effects * 0.02 * frames  # 20ms per effect per frame
        expr_time = expressions * 0.001 * frames  # 1ms per expression per frame
        return base + effect_time + expr_time

    def _identify_heavy_effects(self, effects: List[str]) -> List[str]:
        """Identify computationally expensive effects."""
        heavy = []
        heavy_patterns = [
            'particle', 'particular', '3d', 'element', 'warp', 'blur',
            'glow', 'ray', 'noise', 'fractal', 'liquify', 'mesh',
            'tracker', 'stabilizer', 'roto'
        ]

        for effect in effects:
            effect_lower = effect.lower()
            if any(pattern in effect_lower for pattern in heavy_patterns):
                heavy.append(effect)

        return heavy

    def _calculate_priorities(self) -> None:
        """Calculate priority scores for all candidates."""
        for candidate in self.candidates.values():
            score = 0.0

            # Static bonus
            if candidate.is_static:
                score += 2.0

            # Expression complexity bonus
            if candidate.expression_count > 50:
                score += 5.0
            elif candidate.expression_count > 20:
                score += 3.0

            # Effect complexity bonus
            if candidate.effect_count > 10:
                score += 4.0
            elif candidate.effect_count > 5:
                score += 2.0

            # Repeated use multiplier
            score *= candidate.times_used

            # Render time factor
            if candidate.estimated_render_time > 60:  # More than 1 minute
                score += 3.0

            candidate.priority_score = score

            # Assign priority level
            if score >= 8:
                candidate.priority = PreRenderPriority.CRITICAL
            elif score >= 5:
                candidate.priority = PreRenderPriority.HIGH
            elif score >= 2:
                candidate.priority = PreRenderPriority.MEDIUM
            else:
                candidate.priority = PreRenderPriority.LOW

    def get_recommended_prerender(self, max_time_budget: float = 300.0) -> List[PreRenderCandidate]:
        """
        Get list of candidates worth pre-rendering within time budget.

        Args:
            max_time_budget: Maximum seconds to spend on pre-rendering

        Returns:
            List of candidates to pre-render, in order
        """
        candidates = self.analyze()

        # Filter to worthwhile candidates
        worthwhile = [
            c for c in candidates
            if c.priority.value >= PreRenderPriority.MEDIUM.value
            and c.estimated_render_time > 0
            and c.total_savings_if_cached > c.estimated_render_time * 0.5  # At least 50% savings
        ]

        # Select within budget
        selected = []
        total_time = 0.0

        for candidate in worthwhile:
            if total_time + candidate.estimated_render_time <= max_time_budget:
                selected.append(candidate)
                total_time += candidate.estimated_render_time

        return selected


class PreRenderScheduler:
    """
    Schedules and executes pre-render tasks.

    Handles:
    - Dependency ordering
    - Parallel execution where possible
    - Cache management
    - Progress tracking
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.tasks: Dict[str, PreRenderTask] = {}
        self.completed_cache: Dict[str, str] = {}  # cache_key -> path

    def create_plan(self, candidates: List[PreRenderCandidate]) -> PreRenderPlan:
        """Create execution plan from candidates."""
        tasks = []
        execution_order = []
        total_time = 0.0
        total_savings = 0.0
        total_size = 0.0

        # Sort by dependencies (topological sort)
        ordered = self._topological_sort(candidates)

        for candidate in ordered:
            task_id = f"task_{candidate.id}"
            cache_key = self._compute_cache_key(candidate)

            task = PreRenderTask(
                id=task_id,
                candidate=candidate,
                cache_key=cache_key,
                output_path=str(self.cache_dir / cache_key)
            )

            tasks.append(task)
            execution_order.append(task_id)
            self.tasks[task_id] = task

            total_time += candidate.estimated_render_time
            total_savings += candidate.total_savings_if_cached
            total_size += candidate.cache_size_estimate_mb

        return PreRenderPlan(
            tasks=tasks,
            execution_order=execution_order,
            total_estimated_time=total_time,
            total_estimated_savings=total_savings,
            total_cache_size_mb=total_size
        )

    def _topological_sort(self, candidates: List[PreRenderCandidate]) -> List[PreRenderCandidate]:
        """Sort candidates by dependencies."""
        # Build dependency graph
        in_degree = {c.id: len(c.depends_on) for c in candidates}
        graph = {c.id: list(c.required_by) for c in candidates}

        # Kahn's algorithm
        queue = [c for c in candidates if in_degree[c.id] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for dependent_id in graph.get(node.id, []):
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    dependent = next((c for c in candidates if c.id == dependent_id), None)
                    if dependent:
                        queue.append(dependent)

        return result

    def _compute_cache_key(self, candidate: PreRenderCandidate) -> str:
        """Compute unique cache key for a pre-render candidate."""
        key_data = json.dumps({
            "id": candidate.id,
            "name": candidate.name,
            "duration": candidate.duration,
            "frame_count": candidate.frame_count,
            "effect_count": candidate.effect_count,
            "expression_count": candidate.expression_count
        }, sort_keys=True)

        return hashlib.sha256(key_data.encode()).hexdigest()[:16]

    def check_cache(self, cache_key: str) -> Optional[str]:
        """Check if a pre-render is already cached."""
        cache_path = self.cache_dir / cache_key
        if cache_path.exists():
            return str(cache_path)
        return None

    def get_task_status(self, task_id: str) -> Optional[PreRenderTask]:
        """Get status of a pre-render task."""
        return self.tasks.get(task_id)

    def mark_completed(self, task_id: str, output_path: str, size_bytes: int) -> None:
        """Mark a task as completed."""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = PreRenderStatus.COMPLETED
            task.completed_at = time.time()
            task.output_path = output_path
            task.total_size_bytes = size_bytes

            if task.started_at:
                task.actual_render_time = task.completed_at - task.started_at

            if task.cache_key:
                self.completed_cache[task.cache_key] = output_path

    def mark_failed(self, task_id: str, error: str) -> None:
        """Mark a task as failed."""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = PreRenderStatus.FAILED
            task.error_message = error
            task.retry_count += 1


def analyze_for_prerender(manifest: dict) -> dict:
    """
    High-level API: Analyze manifest for pre-render opportunities.

    Returns dict with:
    - candidates: List of pre-render candidates
    - recommended: Candidates recommended for pre-rendering
    - estimated_savings: Time savings from pre-rendering
    - total_prerender_time: Time needed for pre-renders
    """
    analyzer = PreRenderAnalyzer(manifest)
    all_candidates = analyzer.analyze()
    recommended = analyzer.get_recommended_prerender(max_time_budget=600)  # 10 min budget

    total_savings = sum(c.total_savings_if_cached for c in recommended)
    total_prerender = sum(c.estimated_render_time for c in recommended)

    return {
        "candidates": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.layer_type,
                "priority": c.priority.value,
                "priority_name": c.priority.name,
                "is_static": c.is_static,
                "has_expressions": c.has_expressions,
                "expression_count": c.expression_count,
                "effect_count": c.effect_count,
                "estimated_render_time": round(c.estimated_render_time, 2),
                "savings_if_cached": round(c.total_savings_if_cached, 2)
            }
            for c in all_candidates
        ],
        "recommended": [c.id for c in recommended],
        "estimated_savings_seconds": round(total_savings, 2),
        "total_prerender_time_seconds": round(total_prerender, 2),
        "net_benefit_seconds": round(total_savings - total_prerender, 2)
    }
