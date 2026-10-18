"""System resource readings (CPU, memory, GPU) from /proc and /sys.

No GTK here: a SystemReader turns the kernel's files into a Snapshot, and
everything it cannot read stays None, so the interface shows what exists
and hides the rest. Nothing needs root: GPU load on Intel graphics does
(perf counters), so for Intel only the clock is shown.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Temperature sensors that describe the processor, best first, and the
# label of the reading to prefer in each (None: the first one).
CPU_SENSORS = (
    ("coretemp", "Package id 0"),
    ("k10temp", "Tctl"),
    ("zenpower", "Tdie"),
    ("cpu_thermal", None),
    ("soc_thermal", None),
    ("acpitz", None),
)
HOT_CELSIUS = 85
MEMORY_HIGH = 0.90


@dataclass
class GpuInfo:
    name: str
    driver: str
    busy: float | None = None  # percent
    mhz: float | None = None
    max_mhz: float | None = None
    vram_used: int | None = None  # bytes
    vram_total: int | None = None
    temp: float | None = None


@dataclass
class Snapshot:
    cpu_percent: float | None = None
    cores: list[float] = field(default_factory=list)
    cpu_mhz: float | None = None
    cpu_max_mhz: float | None = None
    cpu_temp: float | None = None
    ram_used: int | None = None  # bytes
    ram_total: int | None = None
    swap_used: int | None = None
    swap_total: int | None = None
    gpus: list[GpuInfo] = field(default_factory=list)

    @property
    def ram_fraction(self) -> float | None:
        if self.ram_used is None or not self.ram_total:
            return None
        return self.ram_used / self.ram_total

    @property
    def gpu(self) -> GpuInfo | None:
        """The GPU worth showing first: a dedicated one over integrated graphics."""
        if not self.gpus:
            return None
        return sorted(self.gpus, key=lambda gpu: gpu.driver in ("i915", "xe"))[0]

    def alerts(self) -> set[str]:
        """What is past its limit: "temp" and/or "ram"."""
        found = set()
        temps = [self.cpu_temp] + [gpu.temp for gpu in self.gpus]
        if any(temp is not None and temp >= HOT_CELSIUS for temp in temps):
            found.add("temp")
        if (self.ram_fraction or 0) >= MEMORY_HIGH:
            found.add("ram")
        return found


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _number(path: Path) -> float | None:
    text = _read(path)
    try:
        return float(text) if text else None
    except ValueError:
        return None


class SystemReader:
    def __init__(self, proc: Path = Path("/proc"), sys: Path = Path("/sys")) -> None:
        self.proc = proc
        self.sys = sys
        self.previous: dict[str, tuple[int, int]] = {}  # cpu line -> (busy, total) jiffies
        self.cpu_sensor: Path | None | bool = False  # False: not looked up yet

    def sample(self) -> Snapshot:
        snapshot = Snapshot()
        self.read_cpu_load(snapshot)
        self.read_cpu_clock(snapshot)
        snapshot.cpu_temp = self.read_cpu_temp()
        self.read_memory(snapshot)
        snapshot.gpus = self.read_gpus()
        return snapshot

    # ------------------------------------------------------------------ CPU
    def read_cpu_load(self, snapshot: Snapshot) -> None:
        text = _read(self.proc / "stat")
        if not text:
            return
        current: dict[str, tuple[int, int]] = {}
        for line in text.splitlines():
            if not line.startswith("cpu"):
                break
            name, *values = line.split()
            numbers = [int(value) for value in values[:8]]
            if len(numbers) < 4:
                continue
            idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)  # idle + iowait
            total = sum(numbers)
            current[name] = (total - idle, total)
        loads = {}
        for name, (busy, total) in current.items():
            if name in self.previous:
                busy_delta = busy - self.previous[name][0]
                total_delta = total - self.previous[name][1]
                if total_delta > 0:
                    loads[name] = max(0.0, min(100.0, 100 * busy_delta / total_delta))
        self.previous = current
        snapshot.cpu_percent = loads.get("cpu")
        snapshot.cores = [loads[name] for name in sorted(
            (name for name in loads if name != "cpu"), key=lambda name: int(name[3:]))]

    def read_cpu_clock(self, snapshot: Snapshot) -> None:
        base = self.sys / "devices" / "system" / "cpu"
        speeds, maximums = [], []
        for directory in sorted(base.glob("cpu[0-9]*/cpufreq")):
            current = _number(directory / "scaling_cur_freq")
            if current:
                speeds.append(current / 1000)
            maximum = _number(directory / "cpuinfo_max_freq")
            if maximum:
                maximums.append(maximum / 1000)
        if not speeds:
            # No cpufreq (some virtual machines): /proc/cpuinfo still says it.
            info = _read(self.proc / "cpuinfo") or ""
            speeds = [float(value) for value in re.findall(r"^cpu MHz\s*:\s*([\d.]+)", info, re.M)]
        if speeds:
            snapshot.cpu_mhz = sum(speeds) / len(speeds)
        if maximums:
            snapshot.cpu_max_mhz = max(maximums)

    def find_cpu_sensor(self) -> Path | None:
        sensors = {}
        for hwmon in sorted((self.sys / "class" / "hwmon").glob("hwmon*")):
            name = _read(hwmon / "name")
            if name:
                sensors.setdefault(name, hwmon)
        for name, label in CPU_SENSORS:
            hwmon = sensors.get(name)
            if hwmon is None:
                continue
            inputs = sorted(hwmon.glob("temp*_input"), key=lambda path: int(re.sub(r"\D", "", path.name) or 0))
            if label is not None:
                for path in inputs:
                    if _read(path.with_name(path.name.replace("_input", "_label"))) == label:
                        return path
            if inputs:
                return inputs[0]
        return None

    def read_cpu_temp(self) -> float | None:
        if self.cpu_sensor is False:
            self.cpu_sensor = self.find_cpu_sensor()  # sensors do not come and go
        value = _number(self.cpu_sensor) if self.cpu_sensor else None
        return value / 1000 if value is not None else None

    # --------------------------------------------------------------- memory
    def read_memory(self, snapshot: Snapshot) -> None:
        values = {}
        for line in (_read(self.proc / "meminfo") or "").splitlines():
            key, _, rest = line.partition(":")
            number = rest.split()[0] if rest.split() else ""
            if number.isdigit():
                values[key] = int(number) * 1024
        if "MemTotal" in values and "MemAvailable" in values:
            snapshot.ram_total = values["MemTotal"]
            snapshot.ram_used = values["MemTotal"] - values["MemAvailable"]
        if values.get("SwapTotal"):
            snapshot.swap_total = values["SwapTotal"]
            snapshot.swap_used = values["SwapTotal"] - values.get("SwapFree", 0)

    # ------------------------------------------------------------------ GPU
    def read_gpus(self) -> list[GpuInfo]:
        gpus = []
        for card in sorted((self.sys / "class" / "drm").glob("card[0-9]*")):
            if "-" in card.name:
                continue  # a connector such as card0-eDP-1
            device = card / "device"
            try:
                driver = os.path.basename(os.readlink(device / "driver"))
            except OSError:
                continue
            if driver in ("i915", "xe"):
                gpus.append(self.read_intel(card, driver))
            elif driver == "amdgpu":
                gpus.append(self.read_amd(device))
            elif driver == "nvidia":
                gpus.append(GpuInfo("NVIDIA", driver))  # filled from nvidia-smi
        return gpus

    @staticmethod
    def read_intel(card: Path, driver: str) -> GpuInfo:
        gpu = GpuInfo("Intel", driver)
        gpu.mhz = _number(card / "gt_act_freq_mhz")
        gpu.max_mhz = _number(card / "gt_max_freq_mhz")
        if gpu.mhz is None:  # the xe driver keeps them per tile
            for frequency in sorted((card / "device").glob("tile*/gt*/freq0")):
                gpu.mhz = _number(frequency / "act_freq")
                gpu.max_mhz = _number(frequency / "max_freq")
                break
        return gpu

    @staticmethod
    def read_amd(device: Path) -> GpuInfo:
        gpu = GpuInfo("AMD", "amdgpu")
        gpu.busy = _number(device / "gpu_busy_percent")
        used, total = _number(device / "mem_info_vram_used"), _number(device / "mem_info_vram_total")
        if used is not None and total:
            gpu.vram_used, gpu.vram_total = int(used), int(total)
        levels = re.findall(r"(\d+)\s*Mhz(\s*\*)?", _read(device / "pp_dpm_sclk") or "", re.I)
        if levels:
            gpu.max_mhz = max(float(level) for level, _ in levels)
            gpu.mhz = next((float(level) for level, star in levels if star), None)
        for hwmon in sorted(device.glob("hwmon/hwmon*")):
            value = _number(hwmon / "temp1_input")
            if value is not None:
                gpu.temp = value / 1000
                break
        return gpu


NVIDIA_QUERY = ["nvidia-smi", "--query-gpu=name,utilization.gpu,clocks.gr,clocks.max.gr,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits"]


def parse_nvidia_smi(text: str) -> list[GpuInfo]:
    gpus = []
    for line in text.strip().splitlines():
        fields = [value.strip() for value in line.split(",")]
        if len(fields) != 7:
            continue

        def number(index: int) -> float | None:
            try:
                return float(fields[index])
            except ValueError:
                return None  # "[N/A]"

        used, total = number(4), number(5)
        gpus.append(GpuInfo(
            fields[0] or "NVIDIA", "nvidia", busy=number(1), mhz=number(2), max_mhz=number(3),
            vram_used=int(used * 1024 * 1024) if used is not None else None,
            vram_total=int(total * 1024 * 1024) if total is not None else None,
            temp=number(6),
        ))
    return gpus


# ------------------------------------------------------------------ text

def decimal(value: float, places: int = 1) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def gigabytes(value: int) -> str:
    return decimal(value / 1024 ** 3)


def frequency(mhz: float) -> str:
    return f"{decimal(mhz / 1000)} GHz" if mhz >= 1000 else f"{mhz:.0f} MHz"


STATUS_ITEMS = ("cpu", "freq", "temp", "ram", "gpu")
DEFAULT_STATUS_ITEMS = ("cpu", "freq", "temp", "ram", "gpu")


def status_groups(snapshot: Snapshot, items: tuple[str, ...] | list[str]) -> list[tuple[str, bool]]:
    """Short status-bar texts, each with whether it is past its limit."""
    alerts = snapshot.alerts()
    groups: list[tuple[str, bool]] = []
    cpu = []
    if "cpu" in items and snapshot.cpu_percent is not None:
        cpu.append(f"CPU {snapshot.cpu_percent:.0f}%")
    if "freq" in items and snapshot.cpu_mhz:
        cpu.append(frequency(snapshot.cpu_mhz))
    hot_cpu = snapshot.cpu_temp is not None and snapshot.cpu_temp >= HOT_CELSIUS
    if "temp" in items and snapshot.cpu_temp is not None:
        cpu.append(f"{snapshot.cpu_temp:.0f} °C")
    if cpu:
        if "cpu" not in items:
            cpu[0] = "CPU " + cpu[0]
        groups.append((" · ".join(cpu), hot_cpu))
    if "ram" in items and snapshot.ram_used is not None and snapshot.ram_total:
        groups.append((f"RAM {gigabytes(snapshot.ram_used)}/{gigabytes(snapshot.ram_total)} GB", "ram" in alerts))
    gpu = snapshot.gpu
    if "gpu" in items and gpu is not None:
        parts = []
        if gpu.busy is not None:
            parts.append(f"{gpu.busy:.0f}%")
        if gpu.mhz is not None:
            parts.append(frequency(gpu.mhz))
        if "temp" in items and gpu.temp is not None:
            parts.append(f"{gpu.temp:.0f} °C")
        if parts:
            groups.append(("GPU " + " · ".join(parts), gpu.temp is not None and gpu.temp >= HOT_CELSIUS))
    return groups
