"""
Execution Mode System

Implements the three user-selectable execution modes:

  LOCAL ONLY   - No cloud, maximum local optimization
  SMART        - System chooses optimal execution (default)
  CLOUD ENABLED - Aggressive cloud usage for speed

User must always have agency over where work runs.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from enum import Enum
import json


class ExecutionMode(Enum):
    """User-selectable execution mode."""
    LOCAL_ONLY = "local_only"
    SMART = "smart"
    CLOUD_ENABLED = "cloud_enabled"


class ExecutionDecision(Enum):
    """Actual execution decision made by the system."""
    LOCAL_OPTIMIZED = "local_optimized"
    LOCAL_PARALLEL = "local_parallel"
    HYBRID = "hybrid"
    CLOUD_ASYNC = "cloud_async"
    CLOUD_PRIORITY = "cloud_priority"


@dataclass
class ExecutionOption:
    """A possible execution option presented to the user."""
    decision: ExecutionDecision
    label: str
    description: str

    # Time/cost
    estimated_seconds: float
    estimated_cost_usd: float

    # Details
    details: List[str] = field(default_factory=list)
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)

    # Recommendation
    is_recommended: bool = False
    recommendation_reason: str = ""

    # Execution
    can_execute: bool = True
    blocked_reason: Optional[str] = None


@dataclass
class ModeConfiguration:
    """Configuration for an execution mode."""
    mode: ExecutionMode
    label: str
    description: str
    icon: str

    # Behavior flags
    allow_cloud: bool
    cloud_aggressive: bool = False
    show_cloud_costs: bool = True
    show_time_comparison: bool = True

    # Limits (for cloud modes)
    max_cost_per_job_usd: Optional[float] = None
    daily_cost_limit_usd: Optional[float] = None

    # Local optimization settings
    enable_multicore: bool = True
    enable_gpu_acceleration: bool = True
    enable_prerender: bool = True
    enable_cache_optimization: bool = True


# Default mode configurations
MODE_CONFIGS = {
    ExecutionMode.LOCAL_ONLY: ModeConfiguration(
        mode=ExecutionMode.LOCAL_ONLY,
        label="Local Only",
        description="All rendering happens on your machine. No cloud costs.",
        icon="computer",
        allow_cloud=False,
        show_cloud_costs=False,
        show_time_comparison=False,
        enable_multicore=True,
        enable_gpu_acceleration=True,
        enable_prerender=True,
        enable_cache_optimization=True
    ),
    ExecutionMode.SMART: ModeConfiguration(
        mode=ExecutionMode.SMART,
        label="Smart",
        description="System recommends the best option. You decide.",
        icon="auto_awesome",
        allow_cloud=True,
        cloud_aggressive=False,
        show_cloud_costs=True,
        show_time_comparison=True,
        max_cost_per_job_usd=50.0,
        daily_cost_limit_usd=100.0,
        enable_multicore=True,
        enable_gpu_acceleration=True,
        enable_prerender=True,
        enable_cache_optimization=True
    ),
    ExecutionMode.CLOUD_ENABLED: ModeConfiguration(
        mode=ExecutionMode.CLOUD_ENABLED,
        label="Cloud Enabled",
        description="Use cloud for faster renders and to free your machine.",
        icon="cloud",
        allow_cloud=True,
        cloud_aggressive=True,
        show_cloud_costs=True,
        show_time_comparison=True,
        max_cost_per_job_usd=100.0,
        daily_cost_limit_usd=500.0,
        enable_multicore=True,
        enable_gpu_acceleration=True,
        enable_prerender=False,  # Cloud handles this
        enable_cache_optimization=True
    )
}


@dataclass
class ExecutionPlan:
    """Complete execution plan based on mode and analysis."""
    mode: ExecutionMode
    decision: ExecutionDecision
    selected_option: ExecutionOption

    # All options (for UI display)
    all_options: List[ExecutionOption]

    # Local execution details
    local_workers: int = 1
    local_gpu_enabled: bool = False
    prerender_tasks: List[str] = field(default_factory=list)
    cache_strategy: str = "balanced"

    # Cloud execution details (if applicable)
    cloud_job_id: Optional[str] = None
    cloud_gpu_class: Optional[str] = None

    # Explanation
    summary: str = ""
    why_chosen: str = ""


class ExecutionModeManager:
    """
    Manages execution mode selection and plan generation.

    This is the decision engine that respects user control
    while providing intelligent recommendations.
    """

    def __init__(self, default_mode: ExecutionMode = ExecutionMode.SMART):
        self.current_mode = default_mode
        self.configs = MODE_CONFIGS.copy()
        self._user_overrides: Dict[str, any] = {}

    def set_mode(self, mode: ExecutionMode) -> ModeConfiguration:
        """Set the current execution mode."""
        self.current_mode = mode
        return self.configs[mode]

    def get_mode(self) -> ExecutionMode:
        """Get the current execution mode."""
        return self.current_mode

    def get_config(self, mode: Optional[ExecutionMode] = None) -> ModeConfiguration:
        """Get configuration for a mode."""
        return self.configs[mode or self.current_mode]

    def set_override(self, key: str, value: any) -> None:
        """Set a user override (e.g., custom cost limit)."""
        self._user_overrides[key] = value

    def generate_plan(
        self,
        local_estimate: dict,
        cloud_estimate: Optional[dict],
        hardware_caps: dict,
        optimization_opportunities: List[dict]
    ) -> ExecutionPlan:
        """
        Generate an execution plan based on current mode and analysis.

        This is the main decision point.
        """
        config = self.configs[self.current_mode]
        options = []

        # Always generate local option
        local_option = self._create_local_option(
            local_estimate, hardware_caps, optimization_opportunities
        )
        options.append(local_option)

        # Generate cloud options if allowed
        if config.allow_cloud and cloud_estimate:
            cloud_option = self._create_cloud_option(
                cloud_estimate, local_estimate
            )
            if cloud_option.can_execute:
                options.append(cloud_option)

            # Hybrid option for smart mode
            if self.current_mode == ExecutionMode.SMART:
                hybrid_option = self._create_hybrid_option(
                    local_estimate, cloud_estimate
                )
                if hybrid_option.can_execute:
                    options.append(hybrid_option)

        # Determine recommendation
        recommended = self._determine_recommendation(options, config)
        for opt in options:
            opt.is_recommended = (opt.decision == recommended.decision)

        # Build plan
        decision = recommended.decision if self.current_mode != ExecutionMode.LOCAL_ONLY else ExecutionDecision.LOCAL_OPTIMIZED

        plan = ExecutionPlan(
            mode=self.current_mode,
            decision=decision,
            selected_option=recommended,
            all_options=options,
            local_workers=hardware_caps.get("recommendations", {}).get("render_threads", 4),
            local_gpu_enabled=hardware_caps.get("recommendations", {}).get("can_gpu_accelerate", False),
            cache_strategy="balanced"
        )

        plan.summary = self._create_summary(plan)
        plan.why_chosen = recommended.recommendation_reason

        return plan

    def _create_local_option(
        self,
        local_estimate: dict,
        hardware_caps: dict,
        opportunities: List[dict]
    ) -> ExecutionOption:
        """Create the local execution option."""
        estimated_seconds = local_estimate.get("total_seconds", 0)
        speedup = local_estimate.get("speedup_factor", 1.0)

        # Build details
        details = [
            f"Estimated time: {self._format_time(estimated_seconds)}",
            f"Optimization speedup: {speedup}x",
            f"Cores used: {hardware_caps.get('recommendations', {}).get('render_threads', 'auto')}"
        ]

        optimizations = local_estimate.get("optimizations", [])
        if optimizations:
            details.append(f"Optimizations: {', '.join(optimizations[:3])}")

        pros = [
            "No cost",
            "Your data stays local",
            "Full control"
        ]

        if speedup >= 2:
            pros.append(f"{speedup}x optimized")

        cons = []
        if estimated_seconds > 3600:
            cons.append("Long render time")
        if not hardware_caps.get("recommendations", {}).get("can_gpu_accelerate"):
            cons.append("No GPU acceleration")

        return ExecutionOption(
            decision=ExecutionDecision.LOCAL_OPTIMIZED,
            label="Local Optimized",
            description=f"Render on your machine in ~{self._format_time(estimated_seconds)}",
            estimated_seconds=estimated_seconds,
            estimated_cost_usd=0.0,
            details=details,
            pros=pros,
            cons=cons
        )

    def _create_cloud_option(
        self,
        cloud_estimate: dict,
        local_estimate: dict
    ) -> ExecutionOption:
        """Create the cloud execution option."""
        estimated_seconds = cloud_estimate.get("total_seconds", 0)
        cost = cloud_estimate.get("cost_usd", 0)
        gpu_class = cloud_estimate.get("gpu_class", "unknown")
        speedup = cloud_estimate.get("speedup_vs_local", 1.0)

        local_seconds = local_estimate.get("total_seconds", estimated_seconds)
        time_saved = local_seconds - estimated_seconds

        details = [
            f"Estimated time: {self._format_time(estimated_seconds)}",
            f"Cost: ${cost:.2f}",
            f"GPU: {gpu_class.upper()}"
        ]

        if time_saved > 60:
            details.append(f"Saves {self._format_time(time_saved)} vs local")

        pros = [
            "Faster completion",
            "Frees your machine",
            "Professional GPU hardware"
        ]

        if speedup >= 3:
            pros.append(f"{speedup}x faster than local")

        cons = [
            f"Costs ${cost:.2f}",
            "Requires upload"
        ]

        # Check if blocked by limits
        can_execute = True
        blocked_reason = None

        config = self.configs[self.current_mode]
        if config.max_cost_per_job_usd and cost > config.max_cost_per_job_usd:
            can_execute = False
            blocked_reason = f"Exceeds job limit (${config.max_cost_per_job_usd})"

        return ExecutionOption(
            decision=ExecutionDecision.CLOUD_ASYNC,
            label="Cloud Render",
            description=f"Render in the cloud for ${cost:.2f}",
            estimated_seconds=estimated_seconds,
            estimated_cost_usd=cost,
            details=details,
            pros=pros,
            cons=cons,
            can_execute=can_execute,
            blocked_reason=blocked_reason
        )

    def _create_hybrid_option(
        self,
        local_estimate: dict,
        cloud_estimate: dict
    ) -> ExecutionOption:
        """Create a hybrid local+cloud option."""
        local_seconds = local_estimate.get("total_seconds", 0)
        cloud_seconds = cloud_estimate.get("total_seconds", 0)
        cloud_cost = cloud_estimate.get("cost_usd", 0)

        # Hybrid: do easy parts locally, heavy parts in cloud
        # Estimate 60% local, 40% cloud
        hybrid_seconds = (local_seconds * 0.4) + (cloud_seconds * 0.6)
        hybrid_cost = cloud_cost * 0.4

        details = [
            f"Estimated time: {self._format_time(hybrid_seconds)}",
            f"Cost: ${hybrid_cost:.2f}",
            "Precomps rendered locally, final in cloud"
        ]

        pros = [
            "Balance of speed and cost",
            "Partial local control"
        ]

        cons = [
            "More complex workflow",
            "Still requires some upload"
        ]

        return ExecutionOption(
            decision=ExecutionDecision.HYBRID,
            label="Hybrid",
            description=f"Split between local and cloud for ${hybrid_cost:.2f}",
            estimated_seconds=hybrid_seconds,
            estimated_cost_usd=hybrid_cost,
            details=details,
            pros=pros,
            cons=cons
        )

    def _determine_recommendation(
        self,
        options: List[ExecutionOption],
        config: ModeConfiguration
    ) -> ExecutionOption:
        """Determine which option to recommend."""
        if not options:
            raise ValueError("No execution options available")

        # Filter to executable options
        executable = [o for o in options if o.can_execute]
        if not executable:
            return options[0]  # Return first even if blocked

        # LOCAL_ONLY mode: always local
        if config.mode == ExecutionMode.LOCAL_ONLY:
            local = next((o for o in executable if o.decision == ExecutionDecision.LOCAL_OPTIMIZED), None)
            if local:
                local.recommendation_reason = "Local Only mode selected"
                return local

        # CLOUD_ENABLED mode: prefer cloud for long renders
        if config.mode == ExecutionMode.CLOUD_ENABLED:
            cloud = next((o for o in executable if o.decision == ExecutionDecision.CLOUD_ASYNC), None)
            local = next((o for o in executable if o.decision == ExecutionDecision.LOCAL_OPTIMIZED), None)

            if cloud and local:
                # Cloud if saves significant time
                if cloud.estimated_seconds < local.estimated_seconds * 0.5:
                    cloud.recommendation_reason = "Cloud is significantly faster"
                    return cloud

            if cloud:
                cloud.recommendation_reason = "Cloud Enabled mode prefers cloud"
                return cloud

        # SMART mode: intelligent selection
        # Score each option
        scored = []
        for opt in executable:
            score = 0.0

            # Time factor (prefer faster)
            if opt.estimated_seconds > 0:
                score -= opt.estimated_seconds / 60  # -1 point per minute

            # Cost factor (prefer cheaper)
            score -= opt.estimated_cost_usd * 10  # -10 points per dollar

            # Bonus for local (user control)
            if opt.decision == ExecutionDecision.LOCAL_OPTIMIZED:
                score += 5

            scored.append((opt, score))

        # Sort by score (higher is better)
        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0][0]

        # Set reason
        if best.decision == ExecutionDecision.LOCAL_OPTIMIZED:
            if best.estimated_seconds < 300:
                best.recommendation_reason = "Quick render - local is optimal"
            else:
                best.recommendation_reason = "Local recommended (no cost, good speed)"
        elif best.decision == ExecutionDecision.CLOUD_ASYNC:
            best.recommendation_reason = "Cloud recommended (faster completion)"
        else:
            best.recommendation_reason = "Best balance of time and cost"

        return best

    def _create_summary(self, plan: ExecutionPlan) -> str:
        """Create a user-friendly summary."""
        opt = plan.selected_option

        if plan.mode == ExecutionMode.LOCAL_ONLY:
            return f"Local render: ~{self._format_time(opt.estimated_seconds)}"

        if opt.decision == ExecutionDecision.LOCAL_OPTIMIZED:
            return f"Local optimized: ~{self._format_time(opt.estimated_seconds)} (no cost)"
        elif opt.decision == ExecutionDecision.CLOUD_ASYNC:
            return f"Cloud: ~{self._format_time(opt.estimated_seconds)} (${opt.estimated_cost_usd:.2f})"
        elif opt.decision == ExecutionDecision.HYBRID:
            return f"Hybrid: ~{self._format_time(opt.estimated_seconds)} (${opt.estimated_cost_usd:.2f})"
        else:
            return f"~{self._format_time(opt.estimated_seconds)}"

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as human-readable time."""
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


# Singleton manager
_mode_manager: Optional[ExecutionModeManager] = None


def get_mode_manager() -> ExecutionModeManager:
    """Get the global mode manager instance."""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = ExecutionModeManager()
    return _mode_manager


def get_execution_plan(
    local_estimate: dict,
    cloud_estimate: Optional[dict],
    hardware_caps: dict,
    optimization_opportunities: List[dict],
    mode: Optional[str] = None
) -> dict:
    """
    High-level API: Generate execution plan.

    Args:
        local_estimate: Local render estimate dict
        cloud_estimate: Cloud render estimate dict (optional)
        hardware_caps: Hardware capabilities dict
        optimization_opportunities: List of optimization opportunities
        mode: Override mode ("local_only", "smart", "cloud_enabled")

    Returns:
        Execution plan as dict
    """
    manager = get_mode_manager()

    if mode:
        manager.set_mode(ExecutionMode(mode))

    plan = manager.generate_plan(
        local_estimate,
        cloud_estimate,
        hardware_caps,
        optimization_opportunities
    )

    return {
        "mode": plan.mode.value,
        "decision": plan.decision.value,
        "summary": plan.summary,
        "why_chosen": plan.why_chosen,
        "selected_option": {
            "decision": plan.selected_option.decision.value,
            "label": plan.selected_option.label,
            "description": plan.selected_option.description,
            "estimated_seconds": plan.selected_option.estimated_seconds,
            "estimated_cost_usd": plan.selected_option.estimated_cost_usd,
            "details": plan.selected_option.details,
            "pros": plan.selected_option.pros,
            "cons": plan.selected_option.cons,
            "is_recommended": plan.selected_option.is_recommended,
            "recommendation_reason": plan.selected_option.recommendation_reason
        },
        "all_options": [
            {
                "decision": opt.decision.value,
                "label": opt.label,
                "description": opt.description,
                "estimated_seconds": opt.estimated_seconds,
                "estimated_cost_usd": opt.estimated_cost_usd,
                "is_recommended": opt.is_recommended,
                "can_execute": opt.can_execute,
                "blocked_reason": opt.blocked_reason
            }
            for opt in plan.all_options
        ],
        "execution": {
            "local_workers": plan.local_workers,
            "local_gpu_enabled": plan.local_gpu_enabled,
            "prerender_tasks": plan.prerender_tasks,
            "cache_strategy": plan.cache_strategy
        }
    }


def get_mode_options() -> List[dict]:
    """Get all available mode options for UI display."""
    return [
        {
            "value": mode.value,
            "label": config.label,
            "description": config.description,
            "icon": config.icon,
            "allow_cloud": config.allow_cloud
        }
        for mode, config in MODE_CONFIGS.items()
    ]
