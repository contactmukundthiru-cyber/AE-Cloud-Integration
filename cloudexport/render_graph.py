"""
Render Graph Optimization Engine

Analyzes After Effects composition structure to build a dependency DAG,
identify parallelization opportunities, and optimize render order.

This is the CORE differentiator for local-first optimization.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import hashlib
import json


class NodeType(Enum):
    COMPOSITION = "composition"
    LAYER = "layer"
    EFFECT = "effect"
    PRECOMP = "precomp"
    ASSET = "asset"
    EXPRESSION = "expression"


class OptimizationType(Enum):
    PARALLEL_LAYERS = "parallel_layers"
    PARALLEL_FRAMES = "parallel_frames"
    PRERENDER_STATIC = "prerender_static"
    CACHE_EXPRESSION = "cache_expression"
    SKIP_HIDDEN = "skip_hidden"
    CHUNK_INDEPENDENT = "chunk_independent"


@dataclass
class RenderNode:
    """A node in the render dependency graph."""
    id: str
    node_type: NodeType
    name: str
    parent_id: Optional[str] = None
    dependencies: Set[str] = field(default_factory=set)
    dependents: Set[str] = field(default_factory=set)

    # Timing info
    in_point: float = 0.0
    out_point: float = 0.0
    duration: float = 0.0

    # Render characteristics
    is_static: bool = False
    is_cacheable: bool = True
    has_expressions: bool = False
    expression_complexity: int = 0
    effect_count: int = 0
    estimated_render_time_per_frame: float = 0.0

    # Optimization hints
    can_parallelize: bool = True
    prerender_priority: int = 0

    # Metadata
    metadata: Dict = field(default_factory=dict)


@dataclass
class OptimizationOpportunity:
    """An identified optimization that can be applied."""
    optimization_type: OptimizationType
    affected_nodes: List[str]
    estimated_speedup_factor: float
    description: str
    priority: int  # 1-10, higher is more important
    applicable_modes: List[str] = field(default_factory=lambda: ["local", "smart", "cloud"])


@dataclass
class RenderChunk:
    """A chunk of work that can be executed independently."""
    id: str
    node_ids: List[str]
    frame_start: int
    frame_end: int
    estimated_time_seconds: float
    dependencies: Set[str] = field(default_factory=set)  # Other chunk IDs
    priority: int = 0
    assigned_worker: Optional[str] = None


@dataclass
class RenderPlan:
    """Optimized render execution plan."""
    chunks: List[RenderChunk]
    execution_order: List[List[str]]  # Stages of parallel chunk IDs
    total_estimated_time: float
    parallel_speedup_factor: float
    optimizations_applied: List[OptimizationOpportunity]
    critical_path: List[str]  # Chunk IDs on critical path

    # Resource requirements
    peak_memory_mb: int = 0
    recommended_workers: int = 1
    gpu_beneficial: bool = False


class RenderGraph:
    """
    Directed Acyclic Graph (DAG) representing render dependencies.

    This enables:
    - Identifying parallelizable work
    - Finding static layers to pre-render
    - Detecting expression bottlenecks
    - Calculating optimal render order
    - Splitting work across cores/workers
    """

    def __init__(self):
        self.nodes: Dict[str, RenderNode] = {}
        self.root_id: Optional[str] = None
        self.fps: float = 30.0
        self.total_frames: int = 0
        self.width: int = 1920
        self.height: int = 1080

    def add_node(self, node: RenderNode) -> None:
        """Add a node to the graph."""
        self.nodes[node.id] = node

    def add_dependency(self, node_id: str, depends_on_id: str) -> None:
        """Establish a dependency between nodes."""
        if node_id in self.nodes and depends_on_id in self.nodes:
            self.nodes[node_id].dependencies.add(depends_on_id)
            self.nodes[depends_on_id].dependents.add(node_id)

    def get_node(self, node_id: str) -> Optional[RenderNode]:
        """Get a node by ID."""
        return self.nodes.get(node_id)

    def get_roots(self) -> List[RenderNode]:
        """Get nodes with no dependencies (can start immediately)."""
        return [n for n in self.nodes.values() if not n.dependencies]

    def get_leaves(self) -> List[RenderNode]:
        """Get nodes with no dependents (final outputs)."""
        return [n for n in self.nodes.values() if not n.dependents]

    def topological_sort(self) -> List[str]:
        """Return nodes in dependency order."""
        visited = set()
        order = []

        def visit(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            node = self.nodes.get(node_id)
            if node:
                for dep_id in node.dependencies:
                    visit(dep_id)
                order.append(node_id)

        for node_id in self.nodes:
            visit(node_id)

        return order

    def find_parallel_groups(self) -> List[List[str]]:
        """
        Find groups of nodes that can execute in parallel.
        Returns stages where each stage contains parallelizable nodes.
        """
        stages: List[List[str]] = []
        completed = set()
        remaining = set(self.nodes.keys())

        while remaining:
            # Find all nodes whose dependencies are complete
            ready = []
            for node_id in remaining:
                node = self.nodes[node_id]
                if node.dependencies.issubset(completed):
                    ready.append(node_id)

            if not ready:
                # Cycle detected or error
                break

            stages.append(ready)
            completed.update(ready)
            remaining -= set(ready)

        return stages

    def calculate_critical_path(self) -> Tuple[List[str], float]:
        """
        Find the critical path (longest dependency chain).
        Returns (path_node_ids, total_time).
        """
        # Dynamic programming for longest path
        dist: Dict[str, float] = {}
        pred: Dict[str, Optional[str]] = {}

        order = self.topological_sort()

        for node_id in order:
            node = self.nodes[node_id]
            max_dist = 0.0
            max_pred = None

            for dep_id in node.dependencies:
                if dep_id in dist:
                    dep_time = dist[dep_id] + self.nodes[dep_id].estimated_render_time_per_frame * self.total_frames
                    if dep_time > max_dist:
                        max_dist = dep_time
                        max_pred = dep_id

            dist[node_id] = max_dist
            pred[node_id] = max_pred

        # Find end of critical path
        if not dist:
            return [], 0.0

        end_node = max(dist.keys(), key=lambda x: dist[x] + self.nodes[x].estimated_render_time_per_frame * self.total_frames)

        # Reconstruct path
        path = []
        current = end_node
        while current:
            path.append(current)
            current = pred.get(current)

        path.reverse()
        total_time = dist[end_node] + self.nodes[end_node].estimated_render_time_per_frame * self.total_frames

        return path, total_time

    def identify_static_layers(self) -> List[str]:
        """Identify layers that don't change over time (can be pre-rendered once)."""
        static = []
        for node in self.nodes.values():
            if node.node_type == NodeType.LAYER and node.is_static:
                static.append(node.id)
        return static

    def identify_expression_bottlenecks(self, threshold: int = 10) -> List[str]:
        """Find nodes with high expression complexity."""
        bottlenecks = []
        for node in self.nodes.values():
            if node.has_expressions and node.expression_complexity >= threshold:
                bottlenecks.append(node.id)
        return sorted(bottlenecks, key=lambda x: self.nodes[x].expression_complexity, reverse=True)

    def get_memory_estimate(self) -> int:
        """Estimate peak memory usage in MB."""
        # Base memory for AE
        base_mb = 2048

        # Per-layer overhead
        layer_count = sum(1 for n in self.nodes.values() if n.node_type == NodeType.LAYER)
        layer_mb = layer_count * 50

        # Frame buffer (4 bytes per pixel, RGBA)
        frame_mb = (self.width * self.height * 4 * 2) / (1024 * 1024)  # Double buffer

        # Effect processing overhead
        effect_count = sum(n.effect_count for n in self.nodes.values())
        effect_mb = effect_count * 100

        return int(base_mb + layer_mb + frame_mb + effect_mb)


class RenderGraphBuilder:
    """Builds a RenderGraph from manifest data."""

    @staticmethod
    def from_manifest(manifest: dict) -> RenderGraph:
        """Build render graph from CloudExport manifest."""
        graph = RenderGraph()

        comp = manifest.get('composition', {})
        graph.fps = comp.get('fps', 30.0)
        graph.total_frames = int(comp.get('durationSeconds', 0) * graph.fps)
        graph.width = comp.get('width', 1920)
        graph.height = comp.get('height', 1080)

        # Create root composition node
        root_id = f"comp_{comp.get('name', 'main')}"
        graph.root_id = root_id

        root_node = RenderNode(
            id=root_id,
            node_type=NodeType.COMPOSITION,
            name=comp.get('name', 'Main Comp'),
            duration=comp.get('durationSeconds', 0),
            in_point=comp.get('workAreaStart', 0),
            out_point=comp.get('workAreaStart', 0) + comp.get('workAreaDuration', comp.get('durationSeconds', 0))
        )
        graph.add_node(root_node)

        # Add effect nodes
        effects = manifest.get('effects', [])
        for i, effect_name in enumerate(effects):
            effect_id = f"effect_{i}_{effect_name}"
            effect_node = RenderNode(
                id=effect_id,
                node_type=NodeType.EFFECT,
                name=effect_name,
                parent_id=root_id,
                effect_count=1,
                # Estimate render time based on effect type
                estimated_render_time_per_frame=RenderGraphBuilder._estimate_effect_time(effect_name)
            )
            graph.add_node(effect_node)
            graph.add_dependency(root_id, effect_id)

        # Add asset dependencies
        assets = manifest.get('assets', [])
        for asset in assets:
            asset_id = f"asset_{asset.get('id', asset.get('zipPath', 'unknown'))}"
            asset_node = RenderNode(
                id=asset_id,
                node_type=NodeType.ASSET,
                name=asset.get('zipPath', 'Unknown Asset'),
                is_static=True,
                is_cacheable=True
            )
            graph.add_node(asset_node)
            graph.add_dependency(root_id, asset_id)

        # Expression complexity
        expr_count = manifest.get('expressionsCount', 0)
        if expr_count > 0:
            expr_id = "expressions_aggregate"
            expr_node = RenderNode(
                id=expr_id,
                node_type=NodeType.EXPRESSION,
                name=f"{expr_count} Expressions",
                has_expressions=True,
                expression_complexity=expr_count,
                estimated_render_time_per_frame=0.001 * expr_count  # 1ms per expression per frame
            )
            graph.add_node(expr_node)
            graph.add_dependency(root_id, expr_id)

        # Update root node estimates
        root_node.effect_count = len(effects)
        root_node.has_expressions = expr_count > 0
        root_node.expression_complexity = expr_count
        root_node.estimated_render_time_per_frame = sum(
            n.estimated_render_time_per_frame for n in graph.nodes.values()
        )

        return graph

    @staticmethod
    def _estimate_effect_time(effect_name: str) -> float:
        """Estimate per-frame render time for an effect in seconds."""
        # Heavy effects
        heavy_effects = [
            'CC Particle', 'Particular', 'Element 3D', 'Optical Flares',
            'CC Ball Action', 'CC Mr. Mercury', 'CC Rainfall', 'CC Snowfall',
            'Warp Stabilizer', 'Motion Blur', '3D Camera Tracker',
            'Roto Brush', 'Content-Aware Fill'
        ]

        # Medium effects
        medium_effects = [
            'Gaussian Blur', 'Fast Blur', 'CC Radial Blur', 'Motion Tile',
            'Fractal Noise', 'Turbulent Displace', 'Mesh Warp', 'Liquify',
            'Glow', 'CC Light Rays', 'CC Glass', 'Drop Shadow'
        ]

        effect_lower = effect_name.lower()

        for heavy in heavy_effects:
            if heavy.lower() in effect_lower:
                return 0.1  # 100ms per frame

        for medium in medium_effects:
            if medium.lower() in effect_lower:
                return 0.02  # 20ms per frame

        return 0.005  # 5ms for light effects


class RenderOptimizer:
    """
    Analyzes render graph and produces optimization recommendations.

    This is where the "intelligence" lives - making local rendering
    feel engineered and predictable.
    """

    def __init__(self, graph: RenderGraph):
        self.graph = graph

    def analyze(self) -> List[OptimizationOpportunity]:
        """Identify all optimization opportunities."""
        opportunities = []

        # Check for parallel layer execution
        parallel = self._find_parallel_opportunities()
        opportunities.extend(parallel)

        # Check for static pre-rendering
        static = self._find_prerender_opportunities()
        opportunities.extend(static)

        # Check for expression caching
        expr = self._find_expression_caching()
        opportunities.extend(expr)

        # Check for frame chunking
        chunks = self._find_chunk_opportunities()
        opportunities.extend(chunks)

        # Sort by priority
        opportunities.sort(key=lambda x: x.priority, reverse=True)

        return opportunities

    def _find_parallel_opportunities(self) -> List[OptimizationOpportunity]:
        """Find layers that can render in parallel."""
        opportunities = []
        stages = self.graph.find_parallel_groups()

        for stage in stages:
            if len(stage) > 1:
                # Multiple nodes can run in parallel
                parallelizable = [
                    nid for nid in stage
                    if self.graph.nodes[nid].can_parallelize
                ]
                if len(parallelizable) > 1:
                    speedup = min(len(parallelizable), 4)  # Cap at 4x
                    opportunities.append(OptimizationOpportunity(
                        optimization_type=OptimizationType.PARALLEL_LAYERS,
                        affected_nodes=parallelizable,
                        estimated_speedup_factor=speedup * 0.8,  # 80% efficiency
                        description=f"{len(parallelizable)} layers can render in parallel",
                        priority=8
                    ))

        return opportunities

    def _find_prerender_opportunities(self) -> List[OptimizationOpportunity]:
        """Find static content that can be pre-rendered."""
        opportunities = []
        static_nodes = self.graph.identify_static_layers()

        if static_nodes:
            total_time = sum(
                self.graph.nodes[nid].estimated_render_time_per_frame * self.graph.total_frames
                for nid in static_nodes
            )
            if total_time > 1.0:  # At least 1 second savings
                opportunities.append(OptimizationOpportunity(
                    optimization_type=OptimizationType.PRERENDER_STATIC,
                    affected_nodes=static_nodes,
                    estimated_speedup_factor=1.0 + (total_time / 10.0),  # Proportional benefit
                    description=f"{len(static_nodes)} static layers can be pre-rendered once",
                    priority=9
                ))

        return opportunities

    def _find_expression_caching(self) -> List[OptimizationOpportunity]:
        """Find expressions that can be cached or optimized."""
        opportunities = []
        bottlenecks = self.graph.identify_expression_bottlenecks(threshold=20)

        if bottlenecks:
            opportunities.append(OptimizationOpportunity(
                optimization_type=OptimizationType.CACHE_EXPRESSION,
                affected_nodes=bottlenecks,
                estimated_speedup_factor=1.3,
                description=f"Expression-heavy layers detected; enable expression caching",
                priority=6
            ))

        return opportunities

    def _find_chunk_opportunities(self) -> List[OptimizationOpportunity]:
        """Find opportunities to chunk frame ranges for parallel processing."""
        if self.graph.total_frames < 60:
            return []

        # Can chunk if no frame-to-frame dependencies in expressions
        expr_nodes = [n for n in self.graph.nodes.values() if n.has_expressions]
        can_chunk = not any(n.expression_complexity > 50 for n in expr_nodes)

        if can_chunk:
            chunk_count = min(8, max(2, self.graph.total_frames // 30))
            return [OptimizationOpportunity(
                optimization_type=OptimizationType.CHUNK_INDEPENDENT,
                affected_nodes=[self.graph.root_id] if self.graph.root_id else [],
                estimated_speedup_factor=chunk_count * 0.7,
                description=f"Can split into {chunk_count} frame chunks for parallel rendering",
                priority=10
            )]

        return []

    def create_render_plan(self, worker_count: int = 1, mode: str = "local") -> RenderPlan:
        """
        Create an optimized render plan.

        Args:
            worker_count: Number of parallel workers (cores/processes)
            mode: Execution mode (local, smart, cloud)
        """
        opportunities = self.analyze()
        applicable = [o for o in opportunities if mode in o.applicable_modes]

        # Create chunks based on opportunities
        chunks = self._create_chunks(worker_count, applicable)

        # Calculate execution order (stages of parallel chunks)
        execution_order = self._calculate_execution_order(chunks)

        # Calculate timing
        critical_path, critical_time = self.graph.calculate_critical_path()

        # Estimate total time with parallelization
        sequential_time = sum(c.estimated_time_seconds for c in chunks)
        parallel_time = self._estimate_parallel_time(chunks, worker_count)

        speedup = sequential_time / parallel_time if parallel_time > 0 else 1.0

        return RenderPlan(
            chunks=chunks,
            execution_order=execution_order,
            total_estimated_time=parallel_time,
            parallel_speedup_factor=speedup,
            optimizations_applied=applicable,
            critical_path=[c.id for c in chunks if any(n in critical_path for n in c.node_ids)],
            peak_memory_mb=self.graph.get_memory_estimate(),
            recommended_workers=min(worker_count, len(chunks)),
            gpu_beneficial=any(
                self.graph.nodes[nid].effect_count > 5
                for c in chunks for nid in c.node_ids
                if nid in self.graph.nodes
            )
        )

    def _create_chunks(self, worker_count: int, opportunities: List[OptimizationOpportunity]) -> List[RenderChunk]:
        """Create render chunks based on optimization opportunities."""
        chunks = []

        # Check for frame chunking opportunity
        frame_chunk_opp = next(
            (o for o in opportunities if o.optimization_type == OptimizationType.CHUNK_INDEPENDENT),
            None
        )

        if frame_chunk_opp and self.graph.total_frames > 0:
            # Split into frame ranges
            chunk_count = min(worker_count, max(2, self.graph.total_frames // 30))
            frames_per_chunk = self.graph.total_frames // chunk_count

            for i in range(chunk_count):
                start = i * frames_per_chunk
                end = start + frames_per_chunk if i < chunk_count - 1 else self.graph.total_frames

                # Estimate time for this chunk
                total_per_frame = sum(n.estimated_render_time_per_frame for n in self.graph.nodes.values())
                chunk_time = total_per_frame * (end - start)

                chunks.append(RenderChunk(
                    id=f"chunk_{i}",
                    node_ids=[self.graph.root_id] if self.graph.root_id else [],
                    frame_start=start,
                    frame_end=end,
                    estimated_time_seconds=chunk_time,
                    priority=chunk_count - i  # Earlier chunks have higher priority
                ))
        else:
            # Single chunk for entire render
            total_time = sum(
                n.estimated_render_time_per_frame * self.graph.total_frames
                for n in self.graph.nodes.values()
            )
            chunks.append(RenderChunk(
                id="chunk_0",
                node_ids=list(self.graph.nodes.keys()),
                frame_start=0,
                frame_end=self.graph.total_frames,
                estimated_time_seconds=total_time,
                priority=1
            ))

        return chunks

    def _calculate_execution_order(self, chunks: List[RenderChunk]) -> List[List[str]]:
        """Determine which chunks can execute in parallel."""
        # Group chunks by their dependencies
        stages: List[List[str]] = []
        completed = set()
        remaining = {c.id: c for c in chunks}

        while remaining:
            ready = []
            for chunk_id, chunk in remaining.items():
                if chunk.dependencies.issubset(completed):
                    ready.append(chunk_id)

            if not ready:
                # All remaining chunks have unmet dependencies or are independent
                ready = list(remaining.keys())

            stages.append(ready)
            completed.update(ready)
            for r in ready:
                del remaining[r]

        return stages

    def _estimate_parallel_time(self, chunks: List[RenderChunk], worker_count: int) -> float:
        """Estimate total time with parallel execution."""
        if not chunks:
            return 0.0

        # Sort by time (longest first)
        sorted_chunks = sorted(chunks, key=lambda c: c.estimated_time_seconds, reverse=True)

        # Simulate parallel execution
        worker_finish_times = [0.0] * worker_count

        for chunk in sorted_chunks:
            # Assign to worker that finishes earliest
            earliest_idx = worker_finish_times.index(min(worker_finish_times))
            worker_finish_times[earliest_idx] += chunk.estimated_time_seconds

        return max(worker_finish_times)


def analyze_manifest_for_optimization(manifest: dict, worker_count: int = 4, mode: str = "local") -> dict:
    """
    High-level API: Analyze manifest and return optimization report.

    Returns a dict with:
    - opportunities: List of optimization opportunities
    - render_plan: Optimized execution plan
    - local_estimate: Estimated time for local render
    - parallel_estimate: Estimated time with parallelization
    - speedup_factor: Expected speedup from optimization
    - recommendations: Human-readable recommendations
    """
    graph = RenderGraphBuilder.from_manifest(manifest)
    optimizer = RenderOptimizer(graph)

    opportunities = optimizer.analyze()
    plan = optimizer.create_render_plan(worker_count, mode)

    # Calculate estimates
    sequential_time = sum(c.estimated_time_seconds for c in plan.chunks)

    recommendations = []
    for opp in opportunities[:5]:  # Top 5 recommendations
        recommendations.append({
            "type": opp.optimization_type.value,
            "description": opp.description,
            "speedup": f"{opp.estimated_speedup_factor:.1f}x",
            "priority": opp.priority
        })

    return {
        "opportunities": [
            {
                "type": o.optimization_type.value,
                "affected_nodes": o.affected_nodes,
                "speedup_factor": o.estimated_speedup_factor,
                "description": o.description,
                "priority": o.priority
            }
            for o in opportunities
        ],
        "render_plan": {
            "chunk_count": len(plan.chunks),
            "execution_stages": len(plan.execution_order),
            "total_estimated_seconds": plan.total_estimated_time,
            "parallel_speedup": plan.parallel_speedup_factor,
            "peak_memory_mb": plan.peak_memory_mb,
            "recommended_workers": plan.recommended_workers,
            "gpu_beneficial": plan.gpu_beneficial
        },
        "local_estimate_seconds": sequential_time,
        "parallel_estimate_seconds": plan.total_estimated_time,
        "speedup_factor": plan.parallel_speedup_factor,
        "recommendations": recommendations,
        "critical_path_chunks": plan.critical_path
    }
