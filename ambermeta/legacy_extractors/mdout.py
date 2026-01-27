from __future__ import annotations

import re
import os
import glob
import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Sequence

# -------------------------------
# 1. Constants & Lookups
# -------------------------------

THERMOSTATS = {
    0: "Constant Energy (NVE)",
    1: "Berendsen",
    2: "Andersen",
    3: "Langevin",
    9: "Optimized Isokinetic",
    10: "Stochastic Isokinetic"
}

BAROSTATS = {
    0: "None",
    1: "Berendsen",
    2: "Monte Carlo"
}

# -------------------------------
# 2. Welford's Online Statistics Algorithm
# -------------------------------

@dataclass
class StreamingStats:
    """
    Implements Welford's online algorithm for streaming mean and variance.
    Uses O(1) memory regardless of the number of samples.
    """
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0  # Sum of squared differences from the mean

    def add(self, value: float) -> None:
        """Add a new value using Welford's online algorithm."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    @property
    def variance(self) -> float:
        """Population variance."""
        if self.count < 2:
            return 0.0
        return self.m2 / self.count

    @property
    def sample_variance(self) -> float:
        """Sample variance (Bessel's correction)."""
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    @property
    def stdev(self) -> float:
        """Sample standard deviation."""
        return math.sqrt(self.sample_variance)

    def get_stats(self) -> Tuple[Optional[float], Optional[float]]:
        """Return (mean, stdev) tuple compatible with _calc_stats."""
        if self.count == 0:
            return None, None
        if self.count == 1:
            return self.mean, 0.0
        return self.mean, self.stdev


# -------------------------------
# 3. Metadata Dataclasses
# -------------------------------

@dataclass
class ThermoStats:
    """
    Stores accumulated statistics for the entire run based on parsed frames.
    Uses Welford's online algorithm for O(1) memory usage.
    """
    count: int = 0
    time_start: float = 0.0
    time_end: float = 0.0

    # Streaming statistics using Welford's algorithm (O(1) memory)
    _temps: StreamingStats = field(default_factory=StreamingStats)
    _pressures: StreamingStats = field(default_factory=StreamingStats)
    _etots: StreamingStats = field(default_factory=StreamingStats)
    _densities: StreamingStats = field(default_factory=StreamingStats)
    _volumes: StreamingStats = field(default_factory=StreamingStats)

    # First and last values for trajectory tracking
    _first_density: Optional[float] = None
    _last_density: Optional[float] = None
    _first_volume: Optional[float] = None
    _last_volume: Optional[float] = None

    # Energy components (accumulators for mean)
    sum_bond: float = 0.0
    sum_angle: float = 0.0
    sum_dihed: float = 0.0
    sum_vdw: float = 0.0
    sum_elec: float = 0.0

    # Backward-compatible list properties (return empty lists for compatibility)
    @property
    def temps(self) -> List[float]:
        """Backward-compatible property. Use temp_stats for streaming statistics."""
        return []

    @property
    def pressures(self) -> List[float]:
        """Backward-compatible property. Use pressure_stats for streaming statistics."""
        return []

    @property
    def etots(self) -> List[float]:
        """Backward-compatible property. Use etot_stats for streaming statistics."""
        return []

    @property
    def densities(self) -> List[float]:
        """Backward-compatible property. Use density_stats for streaming statistics."""
        return []

    @property
    def volumes(self) -> List[float]:
        """Backward-compatible property. Use volume_stats for streaming statistics."""
        return []

    # Streaming statistics accessors
    @property
    def temp_stats(self) -> StreamingStats:
        return self._temps

    @property
    def pressure_stats(self) -> StreamingStats:
        return self._pressures

    @property
    def etot_stats(self) -> StreamingStats:
        return self._etots

    @property
    def density_stats(self) -> StreamingStats:
        return self._densities

    @property
    def volume_stats(self) -> StreamingStats:
        return self._volumes

    @property
    def first_density(self) -> Optional[float]:
        """First density value from the trajectory."""
        return self._first_density

    @property
    def last_density(self) -> Optional[float]:
        """Last density value from the trajectory."""
        return self._last_density

    @property
    def first_volume(self) -> Optional[float]:
        """First volume value from the trajectory."""
        return self._first_volume

    @property
    def last_volume(self) -> Optional[float]:
        """Last volume value from the trajectory."""
        return self._last_volume

    def add_frame(self, data: Dict[str, Any]):
        self.count += 1

        def get_f(key):
            val = data.get(key)
            if isinstance(val, (float, int)): return float(val)
            return None

        t = get_f('TIME(PS)')
        if t is not None:
            if self.count == 1: self.time_start = t
            self.time_end = t

        if (v := get_f('TEMP(K)')) is not None: self._temps.add(v)
        if (v := get_f('PRESS')) is not None: self._pressures.add(v)
        if (v := get_f('Etot')) is not None: self._etots.add(v)
        if (v := get_f('Density')) is not None:
            self._densities.add(v)
            # Track first and last density values
            if self._first_density is None:
                self._first_density = v
            self._last_density = v
        if (v := get_f('VOLUME')) is not None:
            self._volumes.add(v)
            # Track first and last volume values
            if self._first_volume is None:
                self._first_volume = v
            self._last_volume = v

        self.sum_bond += get_f('BOND') or 0.0
        self.sum_angle += get_f('ANGLE') or 0.0
        self.sum_dihed += get_f('DIHED') or 0.0
        self.sum_vdw += (get_f('VDWAALS') or 0.0) + (get_f('1-4 NB') or 0.0)
        self.sum_elec += (get_f('EELEC') or 0.0) + (get_f('1-4 EEL') or 0.0)

    @property
    def duration_ns(self) -> float:
        # Standard duration (Last - First)
        return (self.time_end - self.time_start) / 1000.0

    @property
    def avg_interval_ps(self) -> float:
        """Estimates the output frequency (dt * ntwx) from the frames."""
        if self.count < 2: return 0.0
        # Simple average interval
        return (self.time_end - self.time_start) / max(1, self.count - 1)

    @property
    def true_coverage_ns(self) -> float:
        """
        Calculates coverage including the final step interval (Fencepost correction).
        (Last - First) + Interval
        """
        if self.count == 0: return 0.0
        interval = self.avg_interval_ps
        if interval == 0: return 0.0 # Single frame
        return (self.time_end - self.time_start + interval) / 1000.0

@dataclass
class MdoutMetadata:
    filename: str

    # --- Administrative ---
    program: str = "SANDER"
    version: str = "Unknown"
    run_date: str = "Unknown"
    gpu_model: str = "None"

    # --- System ---
    natoms: int = 0
    nres: int = 0
    box_type: str = "Vacuum"

    @property
    def n_atoms(self) -> int:
        """Standardized atom count property for consistency across metadata classes."""
        return self.natoms
    
    # --- Configuration ---
    run_type: str = "MD"
    dt: float = 0.001
    nstlim: int = 0
    cutoff: float = 999.0
    thermostat: str = "NVE"
    target_temp: float = 0.0
    barostat: str = "None"
    shake_active: bool = False
    
    # --- Statistics ---
    stats: ThermoStats = field(default_factory=ThermoStats)
    
    # --- Performance ---
    wall_time_seconds: float = 0.0
    ns_per_day: float = 0.0
    finished_properly: bool = False
    
    warnings: List[str] = field(default_factory=list)

# -------------------------------
# 3. Helpers
# -------------------------------

def _parse_value(val_str: str) -> Any:
    val_str = val_str.strip().strip(',')
    if '*******' in val_str: return None
    try:
        if '.' in val_str: return float(val_str)
        return int(val_str)
    except ValueError:
        return val_str

def _extract_key_values(line: str) -> Dict[str, Any]:
    # Matches "Key = Value" or "Key=Value"
    # Keys can contain (), -, .
    pattern = re.compile(r"([A-Za-z0-9_\-\(\)\./]+)\s*=\s*([-\d\.\*]+)")
    matches = pattern.findall(line)
    return {k.strip(): _parse_value(v) for k, v in matches}

def _calc_stats(data_list: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not data_list: return None, None
    if len(data_list) == 1: return data_list[0], 0.0
    return statistics.mean(data_list), statistics.stdev(data_list)

# -------------------------------
# 4. Main Parser
# -------------------------------

def parse_mdout(filepath: str) -> MdoutMetadata:
    md = MdoutMetadata(filename=filepath)
    if not os.path.exists(filepath):
        md.warnings.append("File not found.")
        return md

    with open(filepath, 'r', errors='replace') as f:
        lines = f.readlines()

    in_summary_section = False # To ignore "Averages" and "RMS" blocks
    
    for i, line in enumerate(lines):
        
        # --- 1. Header & Engine ---
        if "PMEMD implementation of SANDER" in line:
            md.program = "PMEMD"
        elif "Amber" in line and "PMEMD" in line:
            md.program = "PMEMD"
        
        if "Release" in line and md.version == "Unknown":
            parts = line.split("Release")
            if len(parts) > 1: md.version = parts[1].split()[0].strip().strip(',')

        if line.startswith("| Run on"):
            md.run_date = line.replace("| Run on", "").strip()
        
        if "CUDA Device Name:" in line:
            md.gpu_model = line.split(":", 1)[1].strip()

        # --- 2. Resource Use (Multi-line) ---
        if "RESOURCE   USE" in line:
            # Scan next few lines for NATOM, NRES
            for offset in range(1, 15):
                if i + offset >= len(lines): break
                sub = lines[i+offset]
                if "CONTROL  DATA" in sub: break
                
                kvs = _extract_key_values(sub)
                if 'NATOM' in kvs: md.natoms = kvs['NATOM']
                if 'NRES' in kvs: md.nres = kvs['NRES']
        
        if "BOX TYPE:" in line:
            md.box_type = line.split(":", 1)[1].strip()

        # --- 3. Control Data ---
        # Parse this section specifically to handle compressed lines like t=1000.0,dt=0.004
        if "nstlim" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'nstlim' in kvs: md.nstlim = kvs['nstlim']
            if 'dt' in kvs: md.dt = kvs['dt']
            
        if "dt" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'dt' in kvs: md.dt = kvs['dt']

        if "cut" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'cut' in kvs: md.cutoff = kvs['cut']
            
        if "ntt" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'ntt' in kvs:
                md.thermostat = THERMOSTATS.get(kvs['ntt'], str(kvs['ntt']))
                
        if "temp0" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'temp0' in kvs: md.target_temp = kvs['temp0']
            
        if "ntp" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'ntp' in kvs:
                md.barostat = BAROSTATS.get(kvs['ntp'], str(kvs['ntp']))
                
        if "ntc" in line and "=" in line:
            kvs = _extract_key_values(line)
            if 'ntc' in kvs and kvs['ntc'] > 1:
                md.shake_active = True

        # --- 4. Frame Processing ---
        if "A V E R A G E S" in line or "R M S  F L U C T U A T I O N S" in line:
            in_summary_section = True
            
        if "NSTEP =" in line and "TIME(PS)" in line:
            if not in_summary_section:
                # Combine this line and next ~9 lines to capture all properties
                combined = line.strip()
                for offset in range(1, 10):
                    if i + offset >= len(lines): break
                    nl = lines[i+offset].strip()
                    if "---" in nl or not nl: break
                    combined += " " + nl
                
                data = _extract_key_values(combined)
                md.stats.add_frame(data)

        # --- 5. Performance ---
        if "Final Performance Info" in line or "TIMINGS" in line:
            in_summary_section = False 
            
        if "Final Performance Info" in line:
            md.finished_properly = True
            
        if "ns/day =" in line:
            kvs = _extract_key_values(line)
            if 'ns/day' in kvs: md.ns_per_day = kvs['ns/day']
            
        if "Total wall time:" in line:
            parts = line.split()
            for idx, p in enumerate(parts):
                if "time:" in p and idx+1 < len(parts):
                    try:
                        md.wall_time_seconds = float(parts[idx+1])
                    except (ValueError, IndexError) as e:
                        md.warnings.append(f"Failed to parse wall time: {e}")

    return md

# -------------------------------
# 5. Summarizers
# -------------------------------

def summarize_single(md: MdoutMetadata) -> str:
    s = []
    fname = os.path.basename(md.filename)
    s.append(f"File: {fname}")
    s.append(f"Program: {md.program} {md.version} ({md.run_date})")
    if md.gpu_model != "None": s.append(f"Hardware: GPU ({md.gpu_model})")
    
    s.append(f"System: {md.natoms:,} atoms, {md.nres:,} residues ({md.box_type})")
    
    conf = f"{md.run_type} | dt={md.dt} ps | cut={md.cutoff} A"
    if md.shake_active: conf += " | SHAKE"
    s.append(f"Config: {conf}")
    
    if md.run_type == "MD":
        ens = f"T={md.target_temp}K ({md.thermostat})"
        if md.barostat != "None": ens += f", P={md.barostat}"
        s.append(f"Ensemble: {ens}")
        
        # Calculate Protocol Duration from Input
        dur_ns = (md.nstlim * md.dt) / 1000.0
        s.append(f"Protocol: {md.nstlim:,} steps ({dur_ns:.3f} ns)")

    # Statistics
    st = md.stats
    if st.count > 0:
        s.append("-" * 30)
        s.append(f"Statistics (Computed over {st.count} frames):")
        # Show actual coverage (including interval)
        s.append(f"  Time:    {st.time_start:.1f} -> {st.time_end:.1f} ps (True Coverage: {st.true_coverage_ns:.3f} ns)")

        # Use streaming statistics with get_stats() method
        t_avg, t_std = st.temp_stats.get_stats()
        if t_avg is not None:
            s.append(f"  Temp:    {t_avg:.2f} +/- {t_std:.2f} K")

        p_avg, p_std = st.pressure_stats.get_stats()
        if p_avg is not None: s.append(f"  Press:   {p_avg:.1f} +/- {p_std:.1f} bar")

        d_avg, d_std = st.density_stats.get_stats()
        if d_avg is not None: s.append(f"  Density: {d_avg:.4f} +/- {d_std:.4f} g/cc")

        e_avg, e_std = st.etot_stats.get_stats()
        if e_avg is not None:
            s.append(f"  Etot:    {e_avg:,.1f} +/- {e_std:,.1f} kcal/mol")
        
        parts = []
        if st.sum_bond: parts.append(f"Bond: {st.sum_bond/st.count:.0f}")
        if st.sum_angle: parts.append(f"Angle: {st.sum_angle/st.count:.0f}")
        if st.sum_dihed: parts.append(f"Dihed: {st.sum_dihed/st.count:.0f}")
        s.append("  Energies (Avg): " + ", ".join(parts))
        
        parts_nb = []
        if st.sum_vdw: parts_nb.append(f"VDW: {st.sum_vdw/st.count:.0f}")
        if st.sum_elec: parts_nb.append(f"Elec: {st.sum_elec/st.count:.0f}")
        s.append("                  " + ", ".join(parts_nb))

    s.append("-" * 30)
    if md.finished_properly:
        s.append("Status: Finished Correctly")
        if md.ns_per_day > 0:
            s.append(f"Performance: {md.ns_per_day:.2f} ns/day")
            s.append(f"Wall Time:   {md.wall_time_seconds/3600.0:.2f} hours")
    else:
        s.append("Status: **Incomplete / Crashed**")
        
    return "\n".join(s)

def analyze_sequence(metadatas: Sequence[MdoutMetadata]) -> str:
    valid = [m for m in metadatas if m.stats.count > 0]
    valid.sort(key=lambda x: x.stats.time_start)
    
    if not valid: return "No valid MD data found."
    
    lines = []
    lines.append(f"--- Production Sequence Analysis ({len(valid)} files) ---")
    
    total_frames = 0
    gaps = 0
    
    # Calculate Total Duration as (Last - First) + Interval
    first_stats = valid[0].stats
    last_stats = valid[-1].stats
    
    # Use the interval from the first valid file as a reference for global math
    interval_ps = first_stats.avg_interval_ps
    if interval_ps == 0 and len(valid) > 1:
        # Fallback if first file is 1 frame
        interval_ps = valid[1].stats.avg_interval_ps 
        
    global_start = first_stats.time_start
    global_end = last_stats.time_end
    
    # Total physical time covered (Start to End + 1 step)
    total_time_ns = (global_end - global_start + interval_ps) / 1000.0
    
    for i in range(len(valid) - 1):
        curr = valid[i]
        next_f = valid[i+1]
        total_frames += curr.stats.count
        
        # Continuity Check
        # Next Start should be Current End + Interval
        curr_int = curr.stats.avg_interval_ps
        expected_start = curr.stats.time_end + curr_int
        actual_start = next_f.stats.time_start
        
        # Tolerance: 10% of interval
        diff = actual_start - expected_start
        if abs(diff) > (curr_int * 0.1) and abs(diff) > 0.1:
            gaps += 1
            lines.append(f"  [Gap] {os.path.basename(curr.filename)} ends {curr.stats.time_end:.1f} | "
                         f"{os.path.basename(next_f.filename)} starts {actual_start:.1f} (Exp: {expected_start:.1f})")
            
    total_frames += valid[-1].stats.count
    
    lines.append(f"Timeline: {global_start:.1f} to {global_end:.1f} ps")
    lines.append(f"Total Simulation Time: {total_time_ns:.3f} ns ({total_frames} frames)")
    
    if gaps == 0:
        lines.append("Continuity: Continuous")
    else:
        lines.append(f"Continuity: {gaps} discontinuities detected")
        
    return "\n".join(lines)

# -------------------------------
# 6. CLI
# -------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse AMBER mdout files.")
    parser.add_argument("inputs", nargs='+', help="Input files")
    parser.add_argument("--sequence-only", action="store_true", help="Sequence summary only")
    args = parser.parse_args()
    
    files = []
    for inp in args.inputs:
        matched = glob.glob(inp)
        if matched: files.extend(matched)
        else: files.append(inp)
    files = sorted(list(set(files)))
    
    print(f"--- Processing {len(files)} files ---\n")
    
    metas = []
    for f in files:
        try:
            md = parse_mdout(f)
            metas.append(md)
            if not args.sequence_only:
                print(summarize_single(md))
                print("="*60)
        except (IOError, OSError, ValueError, FileNotFoundError, UnicodeDecodeError) as e:
            print(f"Error {f}: {e}")
            
    if len(metas) > 1:
        print("\n")
        print(analyze_sequence(metas))
        print("="*60)