"""Select and verify the PyTorch CUDA runtime used by PaperMiner Setup.

The policy is intentionally based on both the NVIDIA driver and GPU compute
capability.  ``torch.cuda.is_available()`` alone is insufficient: it can be
true even when the installed wheel contains no kernel image for the GPU.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


CU128_LAST_PACKAGE_SPEC = (
    "torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0"
)
DEFAULT_PACKAGE_SPEC = "torch torchvision torchaudio"


@dataclass(frozen=True)
class NvidiaGpu:
    index: int
    name: str
    driver_version: str
    memory_mib: int | None = None
    compute_capability: tuple[int, int] | None = None


@dataclass(frozen=True)
class TorchPolicy:
    cuda_index: str
    package_spec: str
    reason: str
    blackwell_present: bool
    gpu_families: tuple[str, ...]
    minimum_driver: str


def version_tuple(value: str | None) -> tuple[int, ...]:
    """Parse the numeric prefix of a CUDA, driver, or package version."""
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))]
    return tuple(parts)


def parse_nvidia_smi_csv(text: str) -> list[NvidiaGpu]:
    """Parse four- or five-column ``nvidia-smi`` CSV output."""
    result: list[NvidiaGpu] = []
    for row in csv.reader(io.StringIO(text or "")):
        if len(row) < 3:
            continue
        try:
            index = int(row[0].strip())
        except ValueError:
            continue
        name = row[1].strip()
        driver_version = row[2].strip()
        memory_mib = None
        if len(row) >= 4:
            match = re.search(r"\d+", row[3])
            memory_mib = int(match.group(0)) if match else None
        compute_capability = None
        if len(row) >= 5:
            capability = version_tuple(row[4])
            if len(capability) >= 2:
                compute_capability = (capability[0], capability[1])
        result.append(
            NvidiaGpu(
                index=index,
                name=name,
                driver_version=driver_version,
                memory_mib=memory_mib,
                compute_capability=compute_capability,
            )
        )
    return result


def classify_gpu_family(gpu: NvidiaGpu) -> str:
    """Return the NVIDIA generation relevant to the wheel policy.

    Product names are checked first because they are easier for users to match
    to Setup's message.  Compute capability is the fallback for professional
    and data-centre products whose names do not contain the GeForce series.
    """
    name = gpu.name.casefold()
    if "blackwell" in name or re.search(r"\brtx\s*50\d{2}\b", name):
        return "RTX 50 / Blackwell"
    if "ada" in name or re.search(r"\brtx\s*40\d{2}\b", name):
        return "RTX 40 / Ada"
    if "ampere" in name or re.search(r"\brtx\s*30\d{2}\b", name):
        return "RTX 30 / Ampere"

    capability = gpu.compute_capability
    if capability:
        if capability[0] >= 10:
            return "Blackwell"
        if capability == (8, 9):
            return "Ada"
        if capability in {(8, 0), (8, 6), (8, 7)}:
            return "Ampere"
    return "Other NVIDIA"


def is_blackwell_gpu(gpu: NvidiaGpu) -> bool:
    """Identify Blackwell, including consumer RTX 50-series devices."""
    return "Blackwell" in classify_gpu_family(gpu)


def _gpu_families(gpus: list[NvidiaGpu]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(classify_gpu_family(gpu) for gpu in gpus))


def choose_torch_policy(gpus: list[NvidiaGpu]) -> TorchPolicy:
    """Choose a wheel channel from GPU architecture and Windows driver."""
    if not gpus:
        return TorchPolicy(
            cuda_index="cpu",
            package_spec=DEFAULT_PACKAGE_SPEC,
            reason="No NVIDIA CUDA GPU was reported.",
            blackwell_present=False,
            gpu_families=(),
            minimum_driver="",
        )

    drivers = [version_tuple(gpu.driver_version) for gpu in gpus]
    driver = min((item for item in drivers if item), default=(0,))
    families = _gpu_families(gpus)
    family_label = ", ".join(families)
    blackwell_present = any(is_blackwell_gpu(gpu) for gpu in gpus)
    if blackwell_present:
        # Current PyTorch uses CUDA 13.0+ for Blackwell. CUDA 12.8 remains a
        # pinned fallback for an R570 driver that cannot run CUDA 13 yet.
        # PyTorch's Windows CUDA 13.0 wheel requires 580.88+. CUDA 12.8 GA on
        # Windows was paired with 570.65. A real per-device kernel probe is
        # still the final authority for every GPU.
        if driver >= (580, 88):
            return TorchPolicy(
                cuda_index="cu130",
                package_spec=DEFAULT_PACKAGE_SPEC,
                reason=(
                    f"{family_label} detected; select the current CUDA 13.0 "
                    "wheel (580.88+ Windows driver)."
                ),
                blackwell_present=True,
                gpu_families=families,
                minimum_driver="580.88",
            )
        if driver >= (570, 65):
            return TorchPolicy(
                cuda_index="cu128",
                package_spec=CU128_LAST_PACKAGE_SPEC,
                reason=(
                    f"{family_label} detected with an R570 driver; select the "
                    "pinned CUDA 12.8 compatibility package set."
                ),
                blackwell_present=True,
                gpu_families=families,
                minimum_driver="570.65",
            )
        return TorchPolicy(
            cuda_index="cpu",
            package_spec=DEFAULT_PACKAGE_SPEC,
            reason=(
                f"{family_label} detected, but the NVIDIA driver is older than "
                "the CUDA 12.8 Windows requirement (570.65)."
            ),
            blackwell_present=True,
            gpu_families=families,
            minimum_driver="570.65",
        )

    if driver >= (560, 76):
        cuda_index = "cu126"
        minimum_driver = "560.76"
    elif driver >= (531, 14):
        cuda_index = "cu121"
        minimum_driver = "531.14"
    elif driver >= (520, 6):
        cuda_index = "cu118"
        minimum_driver = "520.06"
    else:
        cuda_index = "cpu"
        minimum_driver = "520.06"
    return TorchPolicy(
        cuda_index=cuda_index,
        package_spec=DEFAULT_PACKAGE_SPEC,
        reason=(
            f"{family_label} detected; selected {cuda_index} for Windows "
            f"driver {'.'.join(str(item) for item in driver)}."
        ),
        blackwell_present=False,
        gpu_families=families,
        minimum_driver=minimum_driver,
    )


def _find_nvidia_smi(explicit: str | None = None) -> str | None:
    candidates = [explicit, shutil.which("nvidia-smi.exe"), shutil.which("nvidia-smi")]
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidates.append(str(Path(system_root) / "System32" / "nvidia-smi.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def detect_nvidia_gpus(nvidia_smi: str | None = None) -> list[NvidiaGpu]:
    """Query NVIDIA hardware, falling back when ``compute_cap`` is unsupported."""
    executable = _find_nvidia_smi(nvidia_smi)
    if not executable:
        return []
    queries = (
        "index,name,driver_version,memory.total,compute_cap",
        "index,name,driver_version,memory.total",
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    for query in queries:
        try:
            completed = subprocess.run(
                [
                    executable,
                    f"--query-gpu={query}",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                creationflags=creation_flags,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if completed.returncode == 0:
            parsed = parse_nvidia_smi_csv(completed.stdout)
            if parsed:
                return parsed
    return []


_EXPECTED_CUDA_MINIMUMS = {
    "cu118": (11, 8),
    "cu121": (12, 1),
    "cu126": (12, 6),
    "cu128": (12, 8),
    "cu130": (13, 0),
}


def cuda_runtime_meets_policy(runtime: str | None, expected: str) -> bool:
    if expected == "cpu":
        return True
    required = _EXPECTED_CUDA_MINIMUMS.get(expected)
    actual = version_tuple(runtime)
    return bool(required and actual >= required)


def _probe_cuda_device(torch_module: Any, index: int) -> float:
    """Run float32 and float16 kernels, including the conversion MinerU needs."""
    device = f"cuda:{index}"
    values = torch_module.arange(
        1,
        17,
        dtype=torch_module.float32,
        device=device,
    )
    half_values = values.to(dtype=torch_module.float16)
    result = (half_values * 2).float().sum()
    torch_module.cuda.synchronize(index)
    return float(result.item())


def verify_torch_runtime(
    expected: str,
    *,
    torch_module: Any | None = None,
    run_kernels: bool = True,
    require_cpu_wheel: bool = False,
) -> tuple[bool, list[str]]:
    """Verify wheel family and execute a real kernel on every visible GPU."""
    messages: list[str] = []
    try:
        if torch_module is None:
            import torch as torch_module  # type: ignore[no-redef]
    except Exception as exc:
        return False, [f"PyTorch import failed: {exc}"]

    torch_version = str(getattr(torch_module, "__version__", "unknown"))
    runtime = getattr(getattr(torch_module, "version", None), "cuda", None)
    messages.extend((f"PyTorch: {torch_version}", f"CUDA runtime: {runtime}"))
    if expected == "cpu":
        if require_cpu_wheel and runtime:
            messages.append(
                f"Installed CUDA wheel ({runtime}) must be replaced by a CPU "
                "wheel because the detected GPU/driver has no safe CUDA policy."
            )
            return False, messages
        messages.append("CPU policy: CUDA kernel validation is not required.")
        return True, messages

    cuda = getattr(torch_module, "cuda", None)
    device_count = 0
    try:
        if cuda is not None:
            architectures = list(cuda.get_arch_list())
            messages.append("Wheel architectures: " + " ".join(architectures))
            if cuda.is_available():
                device_count = int(cuda.device_count())
                for index in range(device_count):
                    name = str(cuda.get_device_name(index))
                    capability = tuple(cuda.get_device_capability(index))
                    messages.append(
                        f"GPU {index}: {name}; capability={capability}"
                    )
    except Exception as exc:
        messages.append(f"CUDA metadata inspection failed: {exc}")

    if not cuda_runtime_meets_policy(runtime, expected):
        messages.append(
            f"Installed CUDA runtime {runtime} does not satisfy {expected}."
        )
        return False, messages

    try:
        if cuda is None or not cuda.is_available():
            messages.append("torch.cuda.is_available() is false.")
            return False, messages
        if device_count <= 0:
            device_count = int(cuda.device_count())
        if device_count <= 0:
            messages.append("PyTorch reported no CUDA devices.")
            return False, messages
        for index in range(device_count):
            if run_kernels:
                value = _probe_cuda_device(torch_module, index)
                if abs(value - 272.0) > 0.5:
                    raise RuntimeError(f"unexpected kernel result: {value}")
                messages.append(f"GPU {index}: CUDA float16 kernel OK")
    except Exception as exc:
        messages.append(f"CUDA kernel validation failed: {exc}")
        return False, messages
    return True, messages


def _print_policy(gpus: list[NvidiaGpu], policy: TorchPolicy) -> None:
    first = gpus[0] if gpus else None
    print(f"GPU_COUNT={len(gpus)}")
    print(f"GPU_NAME={first.name if first else ''}")
    print(f"DRIVER_VER={first.driver_version if first else ''}")
    print(f"BLACKWELL_PRESENT={1 if policy.blackwell_present else 0}")
    print(f"GPU_FAMILIES={', '.join(policy.gpu_families)}")
    print(f"MINIMUM_DRIVER={policy.minimum_driver}")
    print(f"CUDA_INDEX={policy.cuda_index}")
    print(f"TORCH_PACKAGE_SPEC={policy.package_spec}")
    print(f"POLICY_REASON={policy.reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--nvidia-smi")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--expected", required=True)
    verify_parser.add_argument("--quiet", action="store_true")
    verify_parser.add_argument("--require-cpu-wheel", action="store_true")
    auto_parser = subparsers.add_parser("verify-auto")
    auto_parser.add_argument("--nvidia-smi")
    auto_parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "select":
        gpus = detect_nvidia_gpus(args.nvidia_smi)
        _print_policy(gpus, choose_torch_policy(gpus))
        return 0

    expected = args.expected if args.command == "verify" else None
    require_cpu_wheel = bool(
        args.command == "verify" and args.require_cpu_wheel
    )
    if args.command == "verify-auto":
        gpus = detect_nvidia_gpus(args.nvidia_smi)
        expected = choose_torch_policy(gpus).cuda_index
        require_cpu_wheel = bool(gpus and expected == "cpu")
    ok, messages = verify_torch_runtime(
        str(expected),
        require_cpu_wheel=require_cpu_wheel,
    )
    if not args.quiet:
        for message in messages:
            print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
