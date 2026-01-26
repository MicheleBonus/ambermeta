from __future__ import annotations

import math
import os
import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

HAS_NETCDF = False
NETCDF_BACKEND = "None"

try:  # pragma: no cover - optional dependency
    import netCDF4 as nc  # type: ignore

    HAS_NETCDF = True
    NETCDF_BACKEND = "netCDF4"
except ImportError:  # pragma: no cover - optional dependency
    try:
        from scipy.io import netcdf as nc  # type: ignore

        HAS_NETCDF = True
        NETCDF_BACKEND = "scipy"
    except ImportError:
        nc = None  # type: ignore


@dataclass
class MetadataBase:
    filename: str
    warnings: List[str] = field(default_factory=list)


def _detect_format(filepath: str) -> str:
    with open(filepath, "rb") as f:
        header = f.read(4)
        if header.startswith(b"CDF"):
            return "NetCDF"
    return "ASCII"


def _clean_value(val: str) -> Any:
    val = val.strip().strip(",").strip("\"").strip("'")

    if not val:
        return ""

    if "$" in val:
        return val

    if val.lower() == ".true.":
        return True
    if val.lower() == ".false.":
        return False

    try:
        return int(val)
    except ValueError:
        pass

    try:
        result = float(val.replace("d", "e").replace("D", "E"))
        # Filter out NaN and Inf values as they are invalid for simulation parameters
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except ValueError:
        return val


def _extract_key_values(line: str) -> Dict[str, Any]:
    pattern = re.compile(r"([A-Za-z0-9_\-\(\)\./]+)\s*=\s*([-\d\.\*]+)")
    matches = pattern.findall(line)
    return {k.strip(): _parse_value(v) for k, v in matches}


def _parse_value(val_str: str) -> Any:
    val_str = val_str.strip().strip(",")
    if "*******" in val_str:
        return None
    try:
        if "." in val_str:
            return float(val_str)
        return int(val_str)
    except ValueError:
        return val_str


def _calc_stats(data_list: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not data_list:
        return None, None
    if len(data_list) == 1:
        return data_list[0], 0.0
    return statistics.mean(data_list), statistics.stdev(data_list)


def _calc_volume(lengths: List[float], angles: List[float]) -> float:
    a, b, c = lengths
    alpha, beta, gamma = [math.radians(x) for x in angles]

    term = 1 - math.cos(alpha) ** 2 - math.cos(beta) ** 2 - math.cos(gamma) ** 2 + 2 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
    if term < 0:
        return 0.0
    return a * b * c * math.sqrt(term)


__all__ = [
    "HAS_NETCDF",
    "NETCDF_BACKEND",
    "MetadataBase",
    "_calc_stats",
    "_calc_volume",
    "_clean_value",
    "_detect_format",
    "_extract_key_values",
    "nc",
]
