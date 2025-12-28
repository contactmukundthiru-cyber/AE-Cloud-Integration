"""
Hardware Detection and Capability Analysis

Detects local system capabilities for optimal render scheduling:
- CPU cores and topology
- GPU count, VRAM, and compute capability
- Available RAM
- Disk I/O performance
- After Effects installation details
"""

from __future__ import annotations
import os
import platform
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import json


class GPUVendor(Enum):
    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    APPLE = "apple"
    UNKNOWN = "unknown"


class GPUTier(Enum):
    """GPU performance tier for scheduling decisions."""
    INTEGRATED = "integrated"  # Intel UHD, AMD APU
    ENTRY = "entry"            # GTX 1650, RX 5500
    MIDRANGE = "midrange"      # RTX 3060, RX 6700
    HIGH = "high"              # RTX 3080, RX 6800
    WORKSTATION = "workstation"  # RTX 4090, A4000+


@dataclass
class GPUInfo:
    """Information about a detected GPU."""
    index: int
    name: str
    vendor: GPUVendor
    tier: GPUTier
    vram_mb: int
    compute_capability: Optional[str] = None  # For NVIDIA
    driver_version: Optional[str] = None
    is_primary: bool = False

    # Performance characteristics
    estimated_multiplier: float = 1.0  # vs baseline CPU rendering
    supports_cuda: bool = False
    supports_opencl: bool = False
    supports_metal: bool = False

    @property
    def vram_gb(self) -> float:
        return self.vram_mb / 1024


@dataclass
class CPUInfo:
    """Information about the CPU."""
    name: str
    physical_cores: int
    logical_cores: int
    frequency_mhz: int
    architecture: str

    # AE-relevant characteristics
    recommended_ae_threads: int = 1
    hyperthreading: bool = False

    @property
    def can_multiprocess(self) -> bool:
        return self.physical_cores >= 4


@dataclass
class MemoryInfo:
    """System memory information."""
    total_mb: int
    available_mb: int
    ae_recommended_mb: int = 0

    @property
    def total_gb(self) -> float:
        return self.total_mb / 1024

    @property
    def available_gb(self) -> float:
        return self.available_mb / 1024


@dataclass
class DiskInfo:
    """Disk performance info for cache/scratch decisions."""
    path: str
    total_gb: float
    free_gb: float
    is_ssd: bool = False
    read_speed_mbps: float = 100.0
    write_speed_mbps: float = 100.0


@dataclass
class AEInstallation:
    """After Effects installation details."""
    path: str
    version: str
    aerender_path: str
    is_valid: bool = True
    multiframe_rendering: bool = False  # AE 2022+
    gpu_acceleration: bool = False


@dataclass
class SystemCapabilities:
    """Complete system capability profile."""
    cpu: CPUInfo
    memory: MemoryInfo
    gpus: List[GPUInfo] = field(default_factory=list)
    disks: List[DiskInfo] = field(default_factory=list)
    ae_installation: Optional[AEInstallation] = None
    platform: str = "unknown"

    # Calculated recommendations
    recommended_render_threads: int = 1
    recommended_ram_preview_mb: int = 2048
    can_gpu_accelerate: bool = False
    optimal_scratch_disk: Optional[str] = None

    # Performance tier (for UI display)
    overall_tier: str = "standard"  # low, standard, high, workstation

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "platform": self.platform,
            "cpu": {
                "name": self.cpu.name,
                "physical_cores": self.cpu.physical_cores,
                "logical_cores": self.cpu.logical_cores,
                "frequency_mhz": self.cpu.frequency_mhz,
                "architecture": self.cpu.architecture,
                "recommended_ae_threads": self.cpu.recommended_ae_threads
            },
            "memory": {
                "total_gb": self.memory.total_gb,
                "available_gb": self.memory.available_gb,
                "ae_recommended_mb": self.memory.ae_recommended_mb
            },
            "gpus": [
                {
                    "name": g.name,
                    "vendor": g.vendor.value,
                    "tier": g.tier.value,
                    "vram_gb": g.vram_gb,
                    "is_primary": g.is_primary,
                    "estimated_multiplier": g.estimated_multiplier
                }
                for g in self.gpus
            ],
            "disks": [
                {
                    "path": d.path,
                    "free_gb": d.free_gb,
                    "is_ssd": d.is_ssd
                }
                for d in self.disks
            ],
            "recommendations": {
                "render_threads": self.recommended_render_threads,
                "ram_preview_mb": self.recommended_ram_preview_mb,
                "can_gpu_accelerate": self.can_gpu_accelerate,
                "optimal_scratch_disk": self.optimal_scratch_disk,
                "overall_tier": self.overall_tier
            }
        }


class HardwareDetector:
    """Detects and analyzes system hardware capabilities."""

    @staticmethod
    def detect() -> SystemCapabilities:
        """Detect all system capabilities."""
        system = platform.system().lower()

        cpu = HardwareDetector._detect_cpu()
        memory = HardwareDetector._detect_memory()
        gpus = HardwareDetector._detect_gpus()
        disks = HardwareDetector._detect_disks()
        ae = HardwareDetector._detect_ae_installation()

        capabilities = SystemCapabilities(
            cpu=cpu,
            memory=memory,
            gpus=gpus,
            disks=disks,
            ae_installation=ae,
            platform=system
        )

        # Calculate recommendations
        HardwareDetector._calculate_recommendations(capabilities)

        return capabilities

    @staticmethod
    def _detect_cpu() -> CPUInfo:
        """Detect CPU information."""
        try:
            physical = os.cpu_count() or 1
            logical = physical

            # Try to get more accurate core counts
            system = platform.system().lower()

            if system == "linux":
                try:
                    with open("/proc/cpuinfo", "r") as f:
                        content = f.read()
                    physical = content.count("physical id")
                    if physical == 0:
                        physical = os.cpu_count() // 2 or 1
                    logical = os.cpu_count() or 1
                except:
                    pass
            elif system == "darwin":
                try:
                    physical = int(subprocess.check_output(
                        ["sysctl", "-n", "hw.physicalcpu"]
                    ).decode().strip())
                    logical = int(subprocess.check_output(
                        ["sysctl", "-n", "hw.logicalcpu"]
                    ).decode().strip())
                except:
                    pass
            elif system == "windows":
                try:
                    import winreg
                    key = winreg.OpenKey(
                        winreg.HKEY_LOCAL_MACHINE,
                        r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
                    )
                    name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
                    winreg.CloseKey(key)
                except:
                    name = platform.processor()
            else:
                name = platform.processor()

            name = platform.processor() or "Unknown CPU"

            # Estimate frequency
            freq = 2400  # Default 2.4 GHz
            try:
                if system == "darwin":
                    freq = int(subprocess.check_output(
                        ["sysctl", "-n", "hw.cpufrequency"]
                    ).decode().strip()) // 1_000_000
                elif system == "linux":
                    with open("/proc/cpuinfo", "r") as f:
                        for line in f:
                            if "cpu MHz" in line:
                                freq = int(float(line.split(":")[1].strip()))
                                break
            except:
                pass

            # Recommended threads for AE
            # AE benefits from cores but not hyperthreading
            recommended_threads = min(physical, 16)  # AE caps at 16

            return CPUInfo(
                name=name,
                physical_cores=physical,
                logical_cores=logical,
                frequency_mhz=freq,
                architecture=platform.machine(),
                recommended_ae_threads=recommended_threads,
                hyperthreading=logical > physical
            )
        except Exception:
            return CPUInfo(
                name="Unknown",
                physical_cores=4,
                logical_cores=8,
                frequency_mhz=2400,
                architecture="x86_64",
                recommended_ae_threads=4
            )

    @staticmethod
    def _detect_memory() -> MemoryInfo:
        """Detect system memory."""
        try:
            system = platform.system().lower()

            if system == "linux":
                with open("/proc/meminfo", "r") as f:
                    content = f.read()
                total = 0
                available = 0
                for line in content.split("\n"):
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        available = int(line.split()[1]) // 1024
                return MemoryInfo(total_mb=total, available_mb=available)

            elif system == "darwin":
                total = int(subprocess.check_output(
                    ["sysctl", "-n", "hw.memsize"]
                ).decode().strip()) // (1024 * 1024)

                # Get available memory
                vm_stat = subprocess.check_output(["vm_stat"]).decode()
                free_pages = 0
                for line in vm_stat.split("\n"):
                    if "free" in line.lower() or "inactive" in line.lower():
                        try:
                            pages = int(line.split(":")[1].strip().replace(".", ""))
                            free_pages += pages
                        except:
                            pass
                available = (free_pages * 4096) // (1024 * 1024)

                return MemoryInfo(total_mb=total, available_mb=available)

            elif system == "windows":
                # Use wmic
                output = subprocess.check_output(
                    ["wmic", "OS", "get", "TotalVisibleMemorySize,FreePhysicalMemory", "/Value"]
                ).decode()
                total = 0
                available = 0
                for line in output.split("\n"):
                    if "TotalVisibleMemorySize" in line:
                        total = int(line.split("=")[1].strip()) // 1024
                    elif "FreePhysicalMemory" in line:
                        available = int(line.split("=")[1].strip()) // 1024
                return MemoryInfo(total_mb=total, available_mb=available)

        except Exception:
            pass

        return MemoryInfo(total_mb=8192, available_mb=4096)

    @staticmethod
    def _detect_gpus() -> List[GPUInfo]:
        """Detect available GPUs."""
        gpus = []

        # Try NVIDIA first
        nvidia_gpus = HardwareDetector._detect_nvidia_gpus()
        gpus.extend(nvidia_gpus)

        # Try AMD
        if not gpus:
            amd_gpus = HardwareDetector._detect_amd_gpus()
            gpus.extend(amd_gpus)

        # Try macOS Metal
        if platform.system().lower() == "darwin":
            metal_gpus = HardwareDetector._detect_metal_gpus()
            for mg in metal_gpus:
                if not any(g.name == mg.name for g in gpus):
                    gpus.append(mg)

        # Mark primary
        if gpus:
            gpus[0].is_primary = True

        return gpus

    @staticmethod
    def _detect_nvidia_gpus() -> List[GPUInfo]:
        """Detect NVIDIA GPUs using nvidia-smi."""
        gpus = []
        try:
            output = subprocess.check_output([
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,driver_version,compute_cap",
                "--format=csv,noheader,nounits"
            ], stderr=subprocess.DEVNULL).decode()

            for line in output.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 4:
                    idx = int(parts[0])
                    name = parts[1]
                    vram = int(parts[2])
                    driver = parts[3]
                    compute = parts[4] if len(parts) > 4 else None

                    tier = HardwareDetector._classify_nvidia_tier(name, vram)

                    gpus.append(GPUInfo(
                        index=idx,
                        name=name,
                        vendor=GPUVendor.NVIDIA,
                        tier=tier,
                        vram_mb=vram,
                        compute_capability=compute,
                        driver_version=driver,
                        supports_cuda=True,
                        supports_opencl=True,
                        estimated_multiplier=HardwareDetector._get_gpu_multiplier(tier)
                    ))
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        return gpus

    @staticmethod
    def _detect_amd_gpus() -> List[GPUInfo]:
        """Detect AMD GPUs."""
        gpus = []
        try:
            # Try rocm-smi for Linux
            if platform.system().lower() == "linux":
                output = subprocess.check_output(
                    ["rocm-smi", "--showmeminfo", "vram", "--json"],
                    stderr=subprocess.DEVNULL
                ).decode()
                data = json.loads(output)
                # Parse rocm-smi output
                # This is simplified; real implementation would parse properly
        except:
            pass

        return gpus

    @staticmethod
    def _detect_metal_gpus() -> List[GPUInfo]:
        """Detect macOS Metal GPUs."""
        gpus = []
        try:
            output = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                stderr=subprocess.DEVNULL
            ).decode()
            data = json.loads(output)

            displays = data.get("SPDisplaysDataType", [])
            for idx, display in enumerate(displays):
                name = display.get("sppci_model", "Unknown GPU")
                vram_str = display.get("spdisplays_vram", "0 MB")

                # Parse VRAM
                vram_mb = 0
                if "GB" in vram_str:
                    vram_mb = int(float(vram_str.replace("GB", "").strip()) * 1024)
                elif "MB" in vram_str:
                    vram_mb = int(vram_str.replace("MB", "").strip())

                # Determine vendor and tier
                vendor = GPUVendor.UNKNOWN
                if "AMD" in name or "Radeon" in name:
                    vendor = GPUVendor.AMD
                elif "Intel" in name:
                    vendor = GPUVendor.INTEL
                elif "Apple" in name:
                    vendor = GPUVendor.APPLE

                tier = GPUTier.MIDRANGE
                if "M1" in name or "M2" in name or "M3" in name:
                    if "Pro" in name or "Max" in name or "Ultra" in name:
                        tier = GPUTier.HIGH
                    else:
                        tier = GPUTier.MIDRANGE
                elif "Intel" in name:
                    tier = GPUTier.INTEGRATED

                gpus.append(GPUInfo(
                    index=idx,
                    name=name,
                    vendor=vendor,
                    tier=tier,
                    vram_mb=vram_mb,
                    supports_metal=True,
                    estimated_multiplier=HardwareDetector._get_gpu_multiplier(tier)
                ))
        except:
            pass

        return gpus

    @staticmethod
    def _classify_nvidia_tier(name: str, vram_mb: int) -> GPUTier:
        """Classify NVIDIA GPU into performance tier."""
        name_lower = name.lower()

        # Workstation
        if any(x in name_lower for x in ["a100", "a6000", "a5000", "a4000", "quadro", "rtx 4090", "rtx 4080"]):
            return GPUTier.WORKSTATION

        # High
        if any(x in name_lower for x in ["rtx 3090", "rtx 3080", "rtx 4070", "rtx 3070"]):
            return GPUTier.HIGH

        # Midrange
        if any(x in name_lower for x in ["rtx 3060", "rtx 2070", "rtx 2060", "gtx 1080", "gtx 1070"]):
            return GPUTier.MIDRANGE

        # Entry
        if any(x in name_lower for x in ["gtx 1650", "gtx 1660", "gtx 1050", "mx"]):
            return GPUTier.ENTRY

        # Fallback by VRAM
        if vram_mb >= 16000:
            return GPUTier.WORKSTATION
        elif vram_mb >= 8000:
            return GPUTier.HIGH
        elif vram_mb >= 6000:
            return GPUTier.MIDRANGE
        elif vram_mb >= 4000:
            return GPUTier.ENTRY
        else:
            return GPUTier.INTEGRATED

    @staticmethod
    def _get_gpu_multiplier(tier: GPUTier) -> float:
        """Get estimated render speed multiplier for GPU tier."""
        multipliers = {
            GPUTier.INTEGRATED: 1.0,
            GPUTier.ENTRY: 1.5,
            GPUTier.MIDRANGE: 2.5,
            GPUTier.HIGH: 4.0,
            GPUTier.WORKSTATION: 6.0
        }
        return multipliers.get(tier, 1.0)

    @staticmethod
    def _detect_disks() -> List[DiskInfo]:
        """Detect disk information."""
        disks = []

        # Get common paths
        paths_to_check = ["/", os.path.expanduser("~")]

        if platform.system().lower() == "windows":
            paths_to_check = ["C:\\", "D:\\"]

        for path in paths_to_check:
            try:
                usage = shutil.disk_usage(path)
                total_gb = usage.total / (1024 ** 3)
                free_gb = usage.free / (1024 ** 3)

                # Try to detect if SSD
                is_ssd = HardwareDetector._is_ssd(path)

                disks.append(DiskInfo(
                    path=path,
                    total_gb=total_gb,
                    free_gb=free_gb,
                    is_ssd=is_ssd,
                    read_speed_mbps=550 if is_ssd else 150,
                    write_speed_mbps=500 if is_ssd else 120
                ))
            except:
                pass

        return disks

    @staticmethod
    def _is_ssd(path: str) -> bool:
        """Detect if path is on an SSD."""
        try:
            system = platform.system().lower()

            if system == "linux":
                # Get device for path
                df_output = subprocess.check_output(["df", path]).decode()
                device = df_output.split("\n")[1].split()[0]
                device_name = device.split("/")[-1]

                # Check rotational flag
                rotational_path = f"/sys/block/{device_name}/queue/rotational"
                if os.path.exists(rotational_path):
                    with open(rotational_path, "r") as f:
                        return f.read().strip() == "0"

            elif system == "darwin":
                # macOS - assume SSD for now (most Macs have SSDs)
                return True

            elif system == "windows":
                # Check via PowerShell
                try:
                    output = subprocess.check_output([
                        "powershell",
                        "-Command",
                        f"(Get-PhysicalDisk | Where-Object {{ $_.DeviceID -eq 0 }}).MediaType"
                    ], stderr=subprocess.DEVNULL).decode()
                    return "SSD" in output
                except:
                    pass

        except:
            pass

        return False  # Default to HDD assumption

    @staticmethod
    def _detect_ae_installation() -> Optional[AEInstallation]:
        """Detect After Effects installation."""
        ae_paths = []
        system = platform.system().lower()

        if system == "windows":
            program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
            ae_base = os.path.join(program_files, "Adobe")
            if os.path.exists(ae_base):
                for folder in os.listdir(ae_base):
                    if "After Effects" in folder:
                        ae_path = os.path.join(ae_base, folder)
                        aerender = os.path.join(ae_path, "Support Files", "aerender.exe")
                        if os.path.exists(aerender):
                            ae_paths.append((ae_path, aerender, folder))

        elif system == "darwin":
            apps_dir = "/Applications"
            for folder in os.listdir(apps_dir):
                if "After Effects" in folder:
                    ae_path = os.path.join(apps_dir, folder)
                    aerender = os.path.join(ae_path, "aerender")
                    if os.path.exists(aerender):
                        ae_paths.append((ae_path, aerender, folder))

        if ae_paths:
            # Use most recent version
            ae_paths.sort(key=lambda x: x[2], reverse=True)
            ae_path, aerender, folder = ae_paths[0]

            # Extract version from folder name
            version = "Unknown"
            if "2024" in folder:
                version = "2024"
            elif "2023" in folder:
                version = "2023"
            elif "2022" in folder:
                version = "2022"

            # Check for multi-frame rendering (2022+)
            multiframe = version in ["2022", "2023", "2024"]

            return AEInstallation(
                path=ae_path,
                version=version,
                aerender_path=aerender,
                is_valid=True,
                multiframe_rendering=multiframe,
                gpu_acceleration=True
            )

        return None

    @staticmethod
    def _calculate_recommendations(caps: SystemCapabilities) -> None:
        """Calculate optimal settings based on detected hardware."""

        # Render threads
        # AE multi-frame rendering uses multiple threads
        if caps.ae_installation and caps.ae_installation.multiframe_rendering:
            caps.recommended_render_threads = min(caps.cpu.physical_cores, 16)
        else:
            caps.recommended_render_threads = 1

        # RAM preview allocation
        # Reserve at least 4GB for system + AE
        available_for_preview = caps.memory.total_mb - 4096
        caps.recommended_ram_preview_mb = min(
            max(2048, available_for_preview),
            caps.memory.total_mb * 0.75  # Cap at 75% of total
        )
        caps.memory.ae_recommended_mb = int(caps.recommended_ram_preview_mb)

        # GPU acceleration
        caps.can_gpu_accelerate = len(caps.gpus) > 0 and any(
            g.tier != GPUTier.INTEGRATED for g in caps.gpus
        )

        # Optimal scratch disk
        ssds = [d for d in caps.disks if d.is_ssd and d.free_gb > 50]
        if ssds:
            caps.optimal_scratch_disk = max(ssds, key=lambda d: d.free_gb).path
        elif caps.disks:
            caps.optimal_scratch_disk = max(caps.disks, key=lambda d: d.free_gb).path

        # Overall tier classification
        if caps.gpus and caps.gpus[0].tier == GPUTier.WORKSTATION:
            caps.overall_tier = "workstation"
        elif caps.memory.total_mb >= 32000 and caps.cpu.physical_cores >= 8:
            caps.overall_tier = "high"
        elif caps.memory.total_mb >= 16000 and caps.cpu.physical_cores >= 4:
            caps.overall_tier = "standard"
        else:
            caps.overall_tier = "low"


# Singleton for cached detection
_cached_capabilities: Optional[SystemCapabilities] = None


def get_system_capabilities(force_refresh: bool = False) -> SystemCapabilities:
    """Get system capabilities (cached)."""
    global _cached_capabilities
    if _cached_capabilities is None or force_refresh:
        _cached_capabilities = HardwareDetector.detect()
    return _cached_capabilities


def estimate_local_render_time(
    manifest: dict,
    capabilities: Optional[SystemCapabilities] = None
) -> dict:
    """
    Estimate local render time based on hardware capabilities.

    Returns dict with:
    - estimated_seconds: Total estimated render time
    - per_frame_seconds: Time per frame
    - limiting_factor: What's slowing things down
    - recommendations: How to speed it up
    """
    if capabilities is None:
        capabilities = get_system_capabilities()

    comp = manifest.get('composition', {})
    duration = comp.get('durationSeconds', 0)
    fps = comp.get('fps', 30)
    width = comp.get('width', 1920)
    height = comp.get('height', 1080)
    total_frames = int(duration * fps)

    effects = manifest.get('effects', [])
    expr_count = manifest.get('expressionsCount', 0)

    # Base time per frame (empirical formula)
    # Base: 0.5s per frame at 1080p, scaling with resolution
    resolution_factor = (width * height) / (1920 * 1080)
    base_per_frame = 0.5 * resolution_factor

    # Effect overhead
    effect_overhead = 0.02 * len(effects)  # 20ms per effect

    # Expression overhead
    expr_overhead = 0.001 * expr_count  # 1ms per expression

    # Per-frame time
    per_frame = base_per_frame + effect_overhead + expr_overhead

    # Apply hardware multipliers
    # Multi-core speedup
    if capabilities.ae_installation and capabilities.ae_installation.multiframe_rendering:
        core_speedup = min(capabilities.recommended_render_threads, 8) * 0.7  # 70% efficiency
    else:
        core_speedup = 1.0

    # GPU speedup (for GPU-accelerated effects)
    gpu_speedup = 1.0
    if capabilities.can_gpu_accelerate and capabilities.gpus:
        gpu_speedup = capabilities.gpus[0].estimated_multiplier * 0.5  # 50% of effects benefit

    total_speedup = max(core_speedup, gpu_speedup)

    adjusted_per_frame = per_frame / total_speedup
    estimated_seconds = total_frames * adjusted_per_frame

    # Determine limiting factor
    limiting_factor = "cpu"
    recommendations = []

    if capabilities.memory.available_mb < 8000:
        limiting_factor = "memory"
        recommendations.append("Close other applications to free RAM")

    if not capabilities.can_gpu_accelerate:
        recommendations.append("A dedicated GPU would accelerate effects rendering")

    if capabilities.cpu.physical_cores < 8:
        recommendations.append("More CPU cores would enable faster multi-frame rendering")

    if capabilities.ae_installation and not capabilities.ae_installation.multiframe_rendering:
        recommendations.append("Upgrade to After Effects 2022+ for multi-frame rendering")

    return {
        "estimated_seconds": round(estimated_seconds, 1),
        "per_frame_seconds": round(adjusted_per_frame, 3),
        "total_frames": total_frames,
        "limiting_factor": limiting_factor,
        "speedup_factor": round(total_speedup, 2),
        "recommendations": recommendations,
        "hardware_tier": capabilities.overall_tier
    }
