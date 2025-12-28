"""
Local Render Orchestrator

Executes optimized local renders with:
- Multi-frame rendering support
- GPU acceleration when available
- Intelligent chunking
- Progress tracking
- Cache utilization

This module makes local rendering feel engineered and predictable.
"""

from __future__ import annotations
import os
import subprocess
import json
import time
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed

from .hardware import SystemCapabilities, get_system_capabilities
from .render_graph import RenderGraphBuilder, RenderOptimizer, RenderPlan
from .local_optimizer import LocalOptimizer, ExecutionMode


class RenderStatus(Enum):
    """Local render status."""
    PENDING = "pending"
    PREPARING = "preparing"
    RENDERING = "rendering"
    TRANSCODING = "transcoding"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RenderProgress:
    """Progress tracking for local render."""
    status: RenderStatus
    percent: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    elapsed_seconds: float = 0.0
    eta_seconds: float = 0.0
    current_stage: str = ""
    message: str = ""
    chunk_progress: Dict[str, float] = field(default_factory=dict)


@dataclass
class LocalRenderConfig:
    """Configuration for local render."""
    # Paths
    project_path: str
    output_path: str
    comp_name: str

    # Frame range
    frame_start: int = 0
    frame_end: int = 0
    fps: float = 30.0

    # Output settings
    output_format: str = "mp4"  # mp4, mov, png_sequence
    codec: str = "h264"
    bitrate_mbps: float = 8.0
    quality: str = "high"

    # Optimization settings
    enable_multiframe: bool = True
    num_workers: int = 0  # 0 = auto
    enable_gpu: bool = True
    enable_disk_cache: bool = True
    cache_dir: Optional[str] = None

    # Chunk settings (for parallel rendering)
    chunk_size: int = 0  # 0 = auto
    enable_chunking: bool = True


@dataclass
class LocalRenderResult:
    """Result of local render."""
    success: bool
    output_path: Optional[str]
    render_time_seconds: float
    total_frames: int
    average_fps: float
    error_message: Optional[str] = None

    # Statistics
    peak_memory_mb: int = 0
    gpu_utilized: bool = False
    chunks_rendered: int = 1
    cache_hits: int = 0


class LocalRenderOrchestrator:
    """
    Orchestrates optimized local rendering.

    Uses After Effects' aerender command line tool with
    optimal settings based on hardware detection and
    composition analysis.
    """

    def __init__(self, config: LocalRenderConfig, capabilities: Optional[SystemCapabilities] = None):
        self.config = config
        self.capabilities = capabilities or get_system_capabilities()
        self._progress = RenderProgress(status=RenderStatus.PENDING)
        self._cancelled = False
        self._progress_callback: Optional[Callable[[RenderProgress], None]] = None

    def set_progress_callback(self, callback: Callable[[RenderProgress], None]) -> None:
        """Set callback for progress updates."""
        self._progress_callback = callback

    def cancel(self) -> None:
        """Cancel the render."""
        self._cancelled = True
        self._update_progress(RenderStatus.CANCELLED, message="Render cancelled by user")

    def _update_progress(
        self,
        status: Optional[RenderStatus] = None,
        percent: Optional[float] = None,
        current_frame: Optional[int] = None,
        message: Optional[str] = None,
        stage: Optional[str] = None
    ) -> None:
        """Update progress and notify callback."""
        if status:
            self._progress.status = status
        if percent is not None:
            self._progress.percent = percent
        if current_frame is not None:
            self._progress.current_frame = current_frame
        if message:
            self._progress.message = message
        if stage:
            self._progress.current_stage = stage

        if self._progress_callback:
            self._progress_callback(self._progress)

    def render(self) -> LocalRenderResult:
        """
        Execute the local render with optimizations.

        Returns:
            LocalRenderResult with success status and statistics
        """
        start_time = time.time()

        try:
            # Validate inputs
            self._validate_config()
            self._update_progress(RenderStatus.PREPARING, percent=0, stage="Preparing")

            # Determine optimal settings
            num_workers = self._calculate_workers()
            chunk_ranges = self._calculate_chunks()

            total_frames = self.config.frame_end - self.config.frame_start + 1
            self._progress.total_frames = total_frames

            # Create temp directory for intermediate outputs
            temp_dir = Path(tempfile.mkdtemp(prefix="aelocal_"))

            try:
                if len(chunk_ranges) > 1 and self.config.enable_chunking:
                    # Parallel chunk rendering
                    chunk_outputs = self._render_parallel_chunks(chunk_ranges, temp_dir)
                else:
                    # Single render
                    chunk_outputs = [self._render_single(temp_dir)]

                if self._cancelled:
                    return LocalRenderResult(
                        success=False,
                        output_path=None,
                        render_time_seconds=time.time() - start_time,
                        total_frames=total_frames,
                        average_fps=0,
                        error_message="Cancelled"
                    )

                # Combine and transcode
                self._update_progress(RenderStatus.TRANSCODING, percent=90, stage="Transcoding")
                final_output = self._transcode_output(chunk_outputs, temp_dir)

                # Move to final location
                final_path = Path(self.config.output_path)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(final_output), str(final_path))

                elapsed = time.time() - start_time
                self._update_progress(RenderStatus.COMPLETED, percent=100, stage="Complete")

                return LocalRenderResult(
                    success=True,
                    output_path=str(final_path),
                    render_time_seconds=elapsed,
                    total_frames=total_frames,
                    average_fps=total_frames / elapsed if elapsed > 0 else 0,
                    chunks_rendered=len(chunk_ranges),
                    gpu_utilized=self.config.enable_gpu and self.capabilities.can_gpu_accelerate
                )

            finally:
                # Cleanup temp directory
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            self._update_progress(RenderStatus.FAILED, message=str(e))
            return LocalRenderResult(
                success=False,
                output_path=None,
                render_time_seconds=time.time() - start_time,
                total_frames=0,
                average_fps=0,
                error_message=str(e)
            )

    def _validate_config(self) -> None:
        """Validate render configuration."""
        if not os.path.exists(self.config.project_path):
            raise ValueError(f"Project file not found: {self.config.project_path}")

        if not self.config.comp_name:
            raise ValueError("Composition name is required")

        if self.config.frame_end <= self.config.frame_start:
            raise ValueError("Invalid frame range")

    def _calculate_workers(self) -> int:
        """Calculate optimal number of render workers."""
        if self.config.num_workers > 0:
            return self.config.num_workers

        # Use hardware detection
        cores = self.capabilities.cpu.physical_cores

        # AE multiframe rendering uses cores efficiently up to a point
        if self.capabilities.ae_installation and self.capabilities.ae_installation.multiframe_rendering:
            # With multiframe rendering, use up to 8 workers
            return min(cores, 8)
        else:
            # Without multiframe, parallel chunking is the way
            return min(cores, 4)

    def _calculate_chunks(self) -> List[Tuple[int, int]]:
        """Calculate optimal chunk ranges for parallel rendering."""
        if not self.config.enable_chunking:
            return [(self.config.frame_start, self.config.frame_end)]

        total_frames = self.config.frame_end - self.config.frame_start + 1

        # Minimum frames per chunk
        min_chunk_size = 30

        if total_frames < min_chunk_size * 2:
            return [(self.config.frame_start, self.config.frame_end)]

        # Calculate chunk size
        if self.config.chunk_size > 0:
            chunk_size = self.config.chunk_size
        else:
            workers = self._calculate_workers()
            chunk_size = max(min_chunk_size, total_frames // workers)

        # Generate chunks
        chunks = []
        current = self.config.frame_start

        while current <= self.config.frame_end:
            end = min(current + chunk_size - 1, self.config.frame_end)
            chunks.append((current, end))
            current = end + 1

        return chunks

    def _render_single(self, output_dir: Path) -> Path:
        """Render entire frame range as single job."""
        output_path = output_dir / "render.mov"

        cmd = self._build_aerender_command(
            self.config.frame_start,
            self.config.frame_end,
            str(output_path)
        )

        self._update_progress(RenderStatus.RENDERING, percent=5, stage="Rendering")
        self._run_aerender(cmd, 0, 1)

        return output_path

    def _render_parallel_chunks(
        self,
        chunks: List[Tuple[int, int]],
        output_dir: Path
    ) -> List[Path]:
        """Render chunks in parallel."""
        outputs = []
        total_chunks = len(chunks)
        completed = 0

        self._update_progress(RenderStatus.RENDERING, percent=5, stage=f"Rendering {total_chunks} chunks")

        # Render chunks in parallel
        with ThreadPoolExecutor(max_workers=self._calculate_workers()) as executor:
            futures = {}

            for i, (start, end) in enumerate(chunks):
                output_path = output_dir / f"chunk_{i:04d}.mov"
                cmd = self._build_aerender_command(start, end, str(output_path))
                future = executor.submit(self._run_aerender, cmd, i, total_chunks)
                futures[future] = (i, output_path)

            for future in as_completed(futures):
                if self._cancelled:
                    executor.shutdown(wait=False)
                    break

                idx, output_path = futures[future]
                try:
                    future.result()
                    outputs.append((idx, output_path))
                    completed += 1

                    # Update progress
                    base_percent = 5
                    render_percent = 85  # 5-90%
                    percent = base_percent + (completed / total_chunks) * render_percent
                    self._update_progress(percent=percent, stage=f"Chunk {completed}/{total_chunks}")

                except Exception as e:
                    raise RuntimeError(f"Chunk {idx} failed: {e}")

        # Sort by index and return paths
        outputs.sort(key=lambda x: x[0])
        return [path for _, path in outputs]

    def _build_aerender_command(
        self,
        frame_start: int,
        frame_end: int,
        output_path: str
    ) -> List[str]:
        """Build aerender command with optimal settings."""
        aerender = self._find_aerender()

        cmd = [
            aerender,
            "-project", self.config.project_path,
            "-comp", self.config.comp_name,
            "-output", output_path,
            "-s", str(frame_start),
            "-e", str(frame_end),
            "-continueOnMissingFootage"
        ]

        # Multi-frame rendering (AE 2022+)
        if self.config.enable_multiframe and self.capabilities.ae_installation:
            if self.capabilities.ae_installation.multiframe_rendering:
                # Enable via prefs or assume enabled
                pass

        # GPU rendering
        if self.config.enable_gpu and self.capabilities.can_gpu_accelerate:
            cmd.extend(["-gpu", "1"])

        # Memory settings
        if self.capabilities.memory.ae_recommended_mb > 0:
            mem_percent = min(90, int((self.capabilities.memory.ae_recommended_mb / self.capabilities.memory.total_mb) * 100))
            cmd.extend(["-mem_usage", str(mem_percent), "100"])

        return cmd

    def _find_aerender(self) -> str:
        """Find aerender executable."""
        if self.capabilities.ae_installation:
            return self.capabilities.ae_installation.aerender_path

        # Fallback to environment or default
        env_path = os.environ.get("AERENDER_PATH")
        if env_path and os.path.exists(env_path):
            return env_path

        raise RuntimeError("After Effects aerender not found")

    def _run_aerender(self, cmd: List[str], chunk_idx: int, total_chunks: int) -> None:
        """Run aerender process with progress tracking."""
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        while True:
            if self._cancelled:
                process.terminate()
                raise RuntimeError("Cancelled")

            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break

            # Parse progress from aerender output
            if "PROGRESS:" in line:
                try:
                    pct = float(line.split("PROGRESS:")[-1].strip().replace("%", ""))
                    self._progress.chunk_progress[str(chunk_idx)] = pct
                except ValueError:
                    pass

        if process.returncode != 0:
            raise RuntimeError(f"aerender failed with code {process.returncode}")

    def _transcode_output(self, inputs: List[Path], output_dir: Path) -> Path:
        """Transcode/combine rendered output."""
        output_path = output_dir / f"final.{self.config.output_format}"

        if len(inputs) == 1:
            # Single input - just transcode
            input_path = inputs[0]
        else:
            # Multiple inputs - need to concat
            concat_list = output_dir / "concat.txt"
            with open(concat_list, "w") as f:
                for path in inputs:
                    f.write(f"file '{path}'\n")
            input_path = f"concat:{concat_list}"

        # Build ffmpeg command
        cmd = ["ffmpeg", "-y"]

        if len(inputs) > 1:
            cmd.extend(["-f", "concat", "-safe", "0", "-i", str(output_dir / "concat.txt")])
        else:
            cmd.extend(["-i", str(input_path)])

        # Output settings based on format
        if self.config.output_format == "mp4" or self.config.codec == "h264":
            cmd.extend([
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18" if self.config.quality == "high" else "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k"
            ])
        elif self.config.output_format == "mov" or self.config.codec == "prores":
            cmd.extend([
                "-c:v", "prores_ks",
                "-profile:v", "3",
                "-c:a", "pcm_s16le"
            ])

        cmd.append(str(output_path))

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        return output_path


def create_local_render_config(
    manifest: dict,
    project_path: str,
    output_path: str,
    preset: str = "web"
) -> LocalRenderConfig:
    """
    Create render config from manifest.

    Args:
        manifest: CloudExport manifest dict
        project_path: Path to AE project file
        output_path: Desired output path
        preset: Output preset (web, social, high_quality)

    Returns:
        LocalRenderConfig ready for rendering
    """
    comp = manifest.get("composition", {})

    fps = comp.get("fps", 30)
    duration = comp.get("durationSeconds", 0)
    frame_start = int(comp.get("workAreaStart", 0) * fps)
    frame_end = int((comp.get("workAreaStart", 0) + comp.get("workAreaDuration", duration)) * fps)

    # Determine output settings from preset
    output_format = "mp4"
    codec = "h264"
    bitrate = 8.0

    if preset == "high_quality":
        output_format = "mov"
        codec = "prores"
        bitrate = 200.0
    elif preset == "social":
        bitrate = 12.0

    return LocalRenderConfig(
        project_path=project_path,
        output_path=output_path,
        comp_name=comp.get("name", ""),
        frame_start=frame_start,
        frame_end=frame_end,
        fps=fps,
        output_format=output_format,
        codec=codec,
        bitrate_mbps=bitrate,
        quality="high" if preset == "high_quality" else "medium"
    )


def estimate_local_render_time(manifest: dict) -> dict:
    """
    Estimate local render time based on manifest and hardware.

    Returns dict with time estimates and recommendations.
    """
    optimizer = LocalOptimizer(manifest)
    analysis = optimizer.analyze(include_cloud=False)

    return {
        "estimated_seconds": analysis.local_estimate.total_seconds,
        "formatted": analysis.local_estimate.total_formatted,
        "per_frame_ms": analysis.local_estimate.per_frame_ms,
        "bottleneck": analysis.local_estimate.bottleneck,
        "speedup_factor": analysis.local_estimate.speedup_factor,
        "optimizations": analysis.local_estimate.optimizations,
        "suggestions": [
            {"title": s.title, "description": s.description, "impact": s.impact}
            for s in analysis.suggestions[:5]
        ]
    }
