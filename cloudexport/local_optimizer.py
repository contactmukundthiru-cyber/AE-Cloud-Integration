"""
Local Render Optimizer

This is the CORE of the local-first philosophy.
Combines render graph analysis with hardware detection to produce
optimal local execution strategies.

"Make After Effects feel engineered, not mystical - even offline."
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import json
import time

from .render_graph import (
    RenderGraph, RenderGraphBuilder, RenderOptimizer,
    OptimizationType, RenderPlan, analyze_manifest_for_optimization
)
from .hardware import (
    SystemCapabilities, get_system_capabilities,
    estimate_local_render_time, GPUTier
)


class ExecutionMode(Enum):
    """User-selectable execution mode."""
    LOCAL_ONLY = "local_only"      # No cloud, all optimization applied locally
    SMART = "smart"                 # System chooses optimal execution
    CLOUD_ENABLED = "cloud_enabled" # Aggressively use cloud for speed


@dataclass
class OptimizationSuggestion:
    """A specific optimization suggestion for the user."""
    category: str  # "performance", "quality", "workflow"
    title: str
    description: str
    impact: str  # "high", "medium", "low"
    automatic: bool  # Can be applied automatically
    action_id: Optional[str] = None  # For automation


@dataclass
class LocalEstimate:
    """Detailed local render estimate."""
    total_seconds: float
    total_formatted: str  # "2 hours 15 minutes"
    per_frame_ms: float
    frame_count: int

    # Breakdown
    render_seconds: float
    transcode_seconds: float
    io_seconds: float

    # What's limiting
    bottleneck: str
    bottleneck_detail: str

    # Optimization potential
    baseline_seconds: float  # Without optimizations
    optimized_seconds: float  # With all optimizations
    speedup_factor: float
    optimizations_applied: List[str]


@dataclass
class CloudEstimate:
    """Cloud render estimate for comparison."""
    total_seconds: float
    total_formatted: str
    cost_usd: float
    gpu_class: str

    # Comparison
    speedup_vs_local: float
    cost_per_minute_saved: float


@dataclass
class ExecutionRecommendation:
    """Complete execution recommendation."""
    recommended_mode: ExecutionMode
    reasoning: str

    local_estimate: LocalEstimate
    cloud_estimate: Optional[CloudEstimate]

    # User-friendly summary
    headline: str  # "Local recommended - 18 min optimized render"
    details: List[str]

    # Specific suggestions
    suggestions: List[OptimizationSuggestion]

    # Hardware context
    hardware_summary: str


class LocalOptimizer:
    """
    Main optimization engine for local-first rendering.

    This class:
    1. Analyzes the composition structure
    2. Detects available hardware
    3. Produces optimization recommendations
    4. Generates execution plans
    5. Provides accurate time estimates
    """

    def __init__(self, manifest: dict, capabilities: Optional[SystemCapabilities] = None):
        self.manifest = manifest
        self.capabilities = capabilities or get_system_capabilities()
        self.graph = RenderGraphBuilder.from_manifest(manifest)
        self.graph_optimizer = RenderOptimizer(self.graph)

    def analyze(self, include_cloud: bool = True) -> ExecutionRecommendation:
        """
        Perform complete analysis and generate recommendation.

        This is the main entry point for optimization analysis.
        """
        # Get local estimate
        local_estimate = self._calculate_local_estimate()

        # Get cloud estimate if requested
        cloud_estimate = None
        if include_cloud:
            cloud_estimate = self._calculate_cloud_estimate()

        # Generate suggestions
        suggestions = self._generate_suggestions()

        # Determine recommended mode
        mode, reasoning = self._determine_recommended_mode(
            local_estimate, cloud_estimate
        )

        # Create headline
        headline = self._create_headline(mode, local_estimate, cloud_estimate)

        # Create details list
        details = self._create_details(local_estimate, cloud_estimate, suggestions)

        # Hardware summary
        hw_summary = self._create_hardware_summary()

        return ExecutionRecommendation(
            recommended_mode=mode,
            reasoning=reasoning,
            local_estimate=local_estimate,
            cloud_estimate=cloud_estimate,
            headline=headline,
            details=details,
            suggestions=suggestions,
            hardware_summary=hw_summary
        )

    def _calculate_local_estimate(self) -> LocalEstimate:
        """Calculate detailed local render estimate."""
        comp = self.manifest.get('composition', {})
        duration = comp.get('durationSeconds', 0)
        fps = comp.get('fps', 30)
        frame_count = int(duration * fps)

        # Get base estimate
        base_estimate = estimate_local_render_time(self.manifest, self.capabilities)

        # Get optimization analysis
        worker_count = self.capabilities.recommended_render_threads
        plan = self.graph_optimizer.create_render_plan(worker_count, "local")

        # Calculate baseline (no optimization)
        baseline_per_frame = base_estimate['per_frame_seconds']
        baseline_seconds = frame_count * baseline_per_frame

        # Calculate optimized time
        optimized_seconds = plan.total_estimated_time
        if optimized_seconds <= 0:
            optimized_seconds = baseline_seconds / max(1, plan.parallel_speedup_factor)

        # Add transcode time (roughly 10% of render time)
        transcode_seconds = optimized_seconds * 0.1

        # Add I/O time (disk writes, etc.)
        io_seconds = frame_count * 0.005  # 5ms per frame for I/O

        total_seconds = optimized_seconds + transcode_seconds + io_seconds

        # Determine bottleneck
        bottleneck, bottleneck_detail = self._identify_bottleneck()

        # Collect applied optimizations
        optimizations = [
            o.optimization_type.value for o in plan.optimizations_applied
        ]

        speedup = baseline_seconds / total_seconds if total_seconds > 0 else 1.0

        return LocalEstimate(
            total_seconds=total_seconds,
            total_formatted=self._format_duration(total_seconds),
            per_frame_ms=round((optimized_seconds / frame_count) * 1000, 1) if frame_count > 0 else 0,
            frame_count=frame_count,
            render_seconds=optimized_seconds,
            transcode_seconds=transcode_seconds,
            io_seconds=io_seconds,
            bottleneck=bottleneck,
            bottleneck_detail=bottleneck_detail,
            baseline_seconds=baseline_seconds,
            optimized_seconds=optimized_seconds,
            speedup_factor=round(speedup, 2),
            optimizations_applied=optimizations
        )

    def _calculate_cloud_estimate(self) -> Optional[CloudEstimate]:
        """Calculate cloud render estimate for comparison."""
        try:
            from .pricing import estimate_cost
        except ImportError:
            # Pricing module not available (missing dependencies)
            return None

        try:
            comp = self.manifest.get('composition', {})
            duration = comp.get('durationSeconds', 0)

            # Get cloud cost estimate
            bundle_size = 100 * 1024 * 1024  # Estimate 100MB bundle
            cost, eta, gpu_class, _ = estimate_cost(
                self.manifest, 'web', bundle_size
            )

            # Calculate speedup vs local
            local_estimate = estimate_local_render_time(self.manifest, self.capabilities)
            speedup = local_estimate['estimated_seconds'] / eta if eta > 0 else 1.0

            # Cost per minute saved
            time_saved = local_estimate['estimated_seconds'] - eta
            cost_per_min = cost / (time_saved / 60) if time_saved > 60 else float('inf')

            return CloudEstimate(
                total_seconds=eta,
                total_formatted=self._format_duration(eta),
                cost_usd=cost,
                gpu_class=gpu_class,
                speedup_vs_local=round(speedup, 2),
                cost_per_minute_saved=round(cost_per_min, 2) if cost_per_min != float('inf') else 0
            )
        except Exception:
            # Cloud estimate failed - return None
            return None

    def _generate_suggestions(self) -> List[OptimizationSuggestion]:
        """Generate actionable optimization suggestions."""
        suggestions = []

        # Analyze graph opportunities
        opportunities = self.graph_optimizer.analyze()

        for opp in opportunities[:5]:  # Top 5
            category = "performance"
            if opp.optimization_type == OptimizationType.PRERENDER_STATIC:
                category = "workflow"

            impact = "high" if opp.priority >= 8 else "medium" if opp.priority >= 5 else "low"

            suggestions.append(OptimizationSuggestion(
                category=category,
                title=opp.optimization_type.value.replace("_", " ").title(),
                description=opp.description,
                impact=impact,
                automatic=True,
                action_id=f"opt_{opp.optimization_type.value}"
            ))

        # Hardware-based suggestions
        if not self.capabilities.can_gpu_accelerate:
            suggestions.append(OptimizationSuggestion(
                category="performance",
                title="GPU Acceleration Unavailable",
                description="A dedicated GPU would significantly speed up effects rendering",
                impact="high",
                automatic=False
            ))

        if self.capabilities.memory.available_mb < 8000:
            suggestions.append(OptimizationSuggestion(
                category="performance",
                title="Low Available Memory",
                description="Close other applications to free up RAM for rendering",
                impact="medium",
                automatic=False
            ))

        # AE version suggestion
        if self.capabilities.ae_installation:
            if not self.capabilities.ae_installation.multiframe_rendering:
                suggestions.append(OptimizationSuggestion(
                    category="workflow",
                    title="Multi-Frame Rendering",
                    description="Upgrade to After Effects 2022+ for multi-frame rendering support",
                    impact="high",
                    automatic=False
                ))

        # Composition-specific suggestions
        expr_count = self.manifest.get('expressionsCount', 0)
        if expr_count > 100:
            suggestions.append(OptimizationSuggestion(
                category="workflow",
                title="Expression-Heavy Composition",
                description=f"{expr_count} expressions detected. Consider pre-composing expression-heavy layers",
                impact="medium",
                automatic=False
            ))

        effects = self.manifest.get('effects', [])
        if len(effects) > 20:
            suggestions.append(OptimizationSuggestion(
                category="performance",
                title="Many Effects Applied",
                description=f"{len(effects)} effects in use. Pre-rendering stable layers could help",
                impact="medium",
                automatic=True,
                action_id="prerender_stable"
            ))

        return suggestions

    def _identify_bottleneck(self) -> Tuple[str, str]:
        """Identify what's limiting render performance."""
        # Check memory
        if self.capabilities.memory.available_mb < 4000:
            return "memory", "Less than 4GB available - AE may need to swap to disk"

        # Check GPU
        if not self.capabilities.can_gpu_accelerate:
            effects = self.manifest.get('effects', [])
            if len(effects) > 10:
                return "gpu", "No GPU acceleration for effect-heavy composition"

        # Check expressions
        expr_count = self.manifest.get('expressionsCount', 0)
        if expr_count > 50:
            return "expressions", f"{expr_count} expressions must evaluate per frame"

        # Check resolution
        comp = self.manifest.get('composition', {})
        width = comp.get('width', 1920)
        height = comp.get('height', 1080)
        if width > 3840 or height > 2160:
            return "resolution", f"High resolution ({width}x{height}) increases memory and processing"

        # Default to CPU
        return "cpu", "Standard CPU-bound render"

    def _determine_recommended_mode(
        self,
        local: LocalEstimate,
        cloud: Optional[CloudEstimate]
    ) -> Tuple[ExecutionMode, str]:
        """Determine the recommended execution mode."""

        # If no cloud estimate, always local
        if cloud is None:
            return ExecutionMode.LOCAL_ONLY, "Cloud comparison not available"

        # Quick renders - always local
        if local.total_seconds < 300:  # Less than 5 minutes
            return ExecutionMode.LOCAL_ONLY, f"Quick render ({local.total_formatted}) - local is optimal"

        # Very long renders where cloud saves hours
        if local.total_seconds > 7200 and cloud.speedup_vs_local > 3:
            return ExecutionMode.SMART, f"Long render - cloud could save {self._format_duration(local.total_seconds - cloud.total_seconds)}"

        # Good local hardware
        if self.capabilities.overall_tier in ["high", "workstation"]:
            if local.speedup_factor >= 2:
                return ExecutionMode.LOCAL_ONLY, f"Good hardware ({self.capabilities.overall_tier}) with {local.speedup_factor}x optimization"

        # Cost consideration
        if cloud.cost_usd > 5 and local.total_seconds < 3600:
            return ExecutionMode.LOCAL_ONLY, f"Local preferred - cloud would cost ${cloud.cost_usd:.2f}"

        # Default to smart if modest speedup available
        if cloud.speedup_vs_local > 2:
            return ExecutionMode.SMART, "Balanced option - system will optimize automatically"

        return ExecutionMode.LOCAL_ONLY, "Local rendering is efficient for this composition"

    def _create_headline(
        self,
        mode: ExecutionMode,
        local: LocalEstimate,
        cloud: Optional[CloudEstimate]
    ) -> str:
        """Create user-friendly headline."""
        if mode == ExecutionMode.LOCAL_ONLY:
            if local.speedup_factor >= 2:
                return f"Local optimized: ~{local.total_formatted} ({local.speedup_factor}x faster)"
            else:
                return f"Local render: ~{local.total_formatted}"
        elif mode == ExecutionMode.SMART:
            if cloud:
                return f"Smart: Local ~{local.total_formatted} or Cloud ~{cloud.total_formatted} (${cloud.cost_usd:.2f})"
            return f"Smart mode: ~{local.total_formatted}"
        else:
            if cloud:
                return f"Cloud: ~{cloud.total_formatted} for ${cloud.cost_usd:.2f}"
            return "Cloud enabled"

    def _create_details(
        self,
        local: LocalEstimate,
        cloud: Optional[CloudEstimate],
        suggestions: List[OptimizationSuggestion]
    ) -> List[str]:
        """Create details list for display."""
        details = []

        # Local details
        details.append(f"Frames: {local.frame_count:,} @ {local.per_frame_ms}ms each")
        details.append(f"Bottleneck: {local.bottleneck_detail}")

        if local.speedup_factor > 1:
            details.append(f"Optimization speedup: {local.speedup_factor}x")

        # Applied optimizations
        if local.optimizations_applied:
            opts = ", ".join(local.optimizations_applied[:3])
            details.append(f"Applied: {opts}")

        # Cloud comparison
        if cloud:
            details.append(f"Cloud alternative: {cloud.total_formatted} for ${cloud.cost_usd:.2f}")

        # Top suggestion
        if suggestions:
            top = suggestions[0]
            details.append(f"Tip: {top.description}")

        return details

    def _create_hardware_summary(self) -> str:
        """Create hardware summary string."""
        parts = []

        parts.append(f"{self.capabilities.cpu.physical_cores} cores")

        mem_gb = self.capabilities.memory.total_mb // 1024
        parts.append(f"{mem_gb}GB RAM")

        if self.capabilities.gpus:
            gpu = self.capabilities.gpus[0]
            parts.append(gpu.name)

        parts.append(f"Tier: {self.capabilities.overall_tier}")

        return " | ".join(parts)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format duration in human-readable form."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{mins}m {secs}s" if secs else f"{mins}m"
        else:
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            return f"{hours}h {mins}m" if mins else f"{hours}h"


def get_optimization_report(manifest: dict, mode: str = "smart") -> dict:
    """
    High-level API: Get complete optimization report.

    Args:
        manifest: CloudExport manifest dict
        mode: Execution mode ("local_only", "smart", "cloud_enabled")

    Returns:
        Complete optimization report as dict
    """
    optimizer = LocalOptimizer(manifest)
    include_cloud = mode != "local_only"
    recommendation = optimizer.analyze(include_cloud=include_cloud)

    return {
        "recommended_mode": recommendation.recommended_mode.value,
        "reasoning": recommendation.reasoning,
        "headline": recommendation.headline,
        "details": recommendation.details,
        "hardware_summary": recommendation.hardware_summary,
        "local_estimate": {
            "total_seconds": recommendation.local_estimate.total_seconds,
            "total_formatted": recommendation.local_estimate.total_formatted,
            "per_frame_ms": recommendation.local_estimate.per_frame_ms,
            "frame_count": recommendation.local_estimate.frame_count,
            "bottleneck": recommendation.local_estimate.bottleneck,
            "bottleneck_detail": recommendation.local_estimate.bottleneck_detail,
            "speedup_factor": recommendation.local_estimate.speedup_factor,
            "optimizations": recommendation.local_estimate.optimizations_applied
        },
        "cloud_estimate": {
            "total_seconds": recommendation.cloud_estimate.total_seconds,
            "total_formatted": recommendation.cloud_estimate.total_formatted,
            "cost_usd": recommendation.cloud_estimate.cost_usd,
            "gpu_class": recommendation.cloud_estimate.gpu_class,
            "speedup_vs_local": recommendation.cloud_estimate.speedup_vs_local
        } if recommendation.cloud_estimate else None,
        "suggestions": [
            {
                "category": s.category,
                "title": s.title,
                "description": s.description,
                "impact": s.impact,
                "automatic": s.automatic,
                "action_id": s.action_id
            }
            for s in recommendation.suggestions
        ]
    }


def quick_estimate(manifest: dict) -> dict:
    """
    Quick estimate without full analysis.
    Use for initial UI display before deep analysis.
    """
    comp = manifest.get('composition', {})
    duration = comp.get('durationSeconds', 0)
    fps = comp.get('fps', 30)
    frames = int(duration * fps)

    # Quick heuristics
    effects = len(manifest.get('effects', []))
    expressions = manifest.get('expressionsCount', 0)

    # Base time: 0.5s per frame, adjusted
    complexity = 1.0 + (effects * 0.05) + (expressions * 0.001)
    base_seconds = frames * 0.5 * complexity

    # Assume 4-core system with some optimization
    optimized_seconds = base_seconds / 2.5

    return {
        "frames": frames,
        "duration_seconds": duration,
        "estimated_seconds": optimized_seconds,
        "formatted": LocalOptimizer._format_duration(optimized_seconds),
        "complexity_factor": round(complexity, 2)
    }
