from __future__ import annotations

import os
import glob
import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Dict, Tuple

# -------------------------------
# 1. Dependency Management
# -------------------------------
HAS_NETCDF = False
NETCDF_BACKEND = "None"

try:
    import netCDF4 as nc
    HAS_NETCDF = True
    NETCDF_BACKEND = "netCDF4"
except ImportError:
    try:
        from scipy.io import netcdf as nc
        HAS_NETCDF = True
        NETCDF_BACKEND = "scipy"
    except ImportError:
        pass

# -------------------------------
# 2. Metadata Dataclass
# -------------------------------

@dataclass
class TrajectoryMetadata:
    filename: str
    file_format: str = "Unknown"  # NetCDF or ASCII
    
    # --- Identification ---
    title: str = "N/A"
    program: str = "Unknown"
    conventions: str = "Unknown"
    
    # --- Dimensions ---
    n_atoms: int = 0
    n_frames: int = 0
    
    # --- Time ---
    has_time: bool = False
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    avg_dt: Optional[float] = None    # Average time step between frames
    total_duration: float = 0.0
    
    # --- Periodic Box ---
    has_box: bool = False
    box_type: str = "None" # Orthogonal, Triclinic
    # Stats [Min, Max, Avg]
    volume_stats: Optional[Tuple[float, float, float]] = None 
    
    # --- Contents ---
    has_coordinates: bool = False
    has_velocities: bool = False
    has_forces: bool = False
    
    # --- Replica Exchange (REMD) ---
    is_remd: bool = False
    remd_types: List[str] = field(default_factory=list) 
    # For T-REMD: Min/Max/Avg target temperatures found in file
    remd_temp_stats: Optional[Tuple[float, float, float]] = None 
    
    warnings: List[str] = field(default_factory=list)

# -------------------------------
# 3. Physics Helpers
# -------------------------------

def _calc_volume_array(lengths: np.ndarray, angles: Optional[np.ndarray]) -> np.ndarray:
    """
    Calculate volumes for an array of box dimensions.
    lengths: (N, 3) array of a,b,c
    angles: (N, 3) array of alpha, beta, gamma (degrees)
    """
    if angles is None:
        # Orthogonal: V = a*b*c
        return np.prod(lengths, axis=1)
    
    # Triclinic
    a = lengths[:, 0]
    b = lengths[:, 1]
    c = lengths[:, 2]
    
    # Convert degrees to radians
    rads = np.radians(angles)
    alpha = rads[:, 0]
    beta  = rads[:, 1]
    gamma = rads[:, 2]
    
    # Formula: V = abc * sqrt(1 - cos^2(a) - cos^2(b) - cos^2(g) + 2cos(a)cos(b)cos(g))
    ca = np.cos(alpha)
    cb = np.cos(beta)
    cg = np.cos(gamma)
    
    term = 1.0 - ca**2 - cb**2 - cg**2 + 2.0*ca*cb*cg
    # Clamp term to 0 to avoid numerical sqrt errors for flat cells
    term = np.maximum(term, 0.0)
    
    return a * b * c * np.sqrt(term)

def _get_nc_attr(obj, attr_name: str, default: str = "Unknown") -> str:
    if not hasattr(obj, attr_name):
        return default
    val = getattr(obj, attr_name)
    if isinstance(val, bytes):
        return val.decode('utf-8', errors='ignore')
    return str(val)

def _detect_format(filepath: str) -> str:
    try:
        with open(filepath, 'rb') as f:
            header = f.read(4)
            if header.startswith(b'CDF'):
                return "NetCDF"
    except Exception:
        pass
    return "ASCII"

# -------------------------------
# 4. NetCDF Parser
# -------------------------------

def _parse_netcdf_trajectory(filepath: str) -> TrajectoryMetadata:
    md = TrajectoryMetadata(filename=filepath, file_format="NetCDF")
    
    if not HAS_NETCDF:
        md.warnings.append("NetCDF library missing.")
        return md

    try:
        # Open
        if NETCDF_BACKEND == "netCDF4":
            ds = nc.Dataset(filepath, 'r')
        else:
            ds = nc.netcdf_file(filepath, 'r', mmap=False)

        try:
            # --- 1. Attributes ---
            md.title = _get_nc_attr(ds, 'title', "N/A")
            md.program = _get_nc_attr(ds, 'program')
            md.conventions = _get_nc_attr(ds, 'Conventions')

            # --- 2. Dimensions ---
            # Robust way to get dimension lengths across different libs
            dims = ds.dimensions
            if 'atom' in dims:
                d = dims['atom']
                md.n_atoms = d.size if hasattr(d, 'size') else (d if isinstance(d, int) else len(d))
            
            # --- 3. Variables & Time ---
            vars_keys = ds.variables.keys()
            
            if 'time' in vars_keys:
                md.has_time = True
                t_var = ds.variables['time']
                # Read all times (1D array, usually small memory footprint)
                times = t_var[:]
                md.n_frames = len(times)
                
                if md.n_frames > 0:
                    md.time_start = float(times[0])
                    md.time_end = float(times[-1])
                    md.total_duration = md.time_end - md.time_start
                    
                    if md.n_frames > 1:
                        # Calculate dt steps
                        deltas = np.diff(times)
                        md.avg_dt = float(np.mean(deltas))
                        
                        # Check for internal consistency
                        if np.std(deltas) > 0.01:
                            md.warnings.append("Variable timestep detected within file.")
            elif 'coordinates' in vars_keys:
                # Fallback if no time variable: check coordinate shape
                md.n_frames = ds.variables['coordinates'].shape[0]

            if 'coordinates' in vars_keys: md.has_coordinates = True
            if 'velocities' in vars_keys: md.has_velocities = True
            if 'forces' in vars_keys: md.has_forces = True

            # --- 4. Box & Volume ---
            if 'cell_lengths' in vars_keys:
                md.has_box = True
                lengths = ds.variables['cell_lengths'][:] # (Frames, 3)
                
                angles = None
                if 'cell_angles' in vars_keys:
                    angles = ds.variables['cell_angles'][:] # (Frames, 3)
                    # Check first frame for triclinic
                    if np.any(np.abs(angles[0] - 90.0) > 0.01):
                        md.box_type = "Triclinic"
                    else:
                        md.box_type = "Orthogonal"
                else:
                    md.box_type = "Orthogonal"

                # Calculate Volumes
                try:
                    vols = _calc_volume_array(lengths, angles)
                    if len(vols) > 0:
                        md.volume_stats = (float(np.min(vols)), float(np.max(vols)), float(np.mean(vols)))
                except Exception as e:
                    md.warnings.append(f"Volume calculation failed: {e}")

            # --- 5. REMD Metadata ---
            # 'temp0' in AMBER NetCDF REMD is the thermostat temperature index
            if 'temp0' in vars_keys:
                md.is_remd = True
                temps = ds.variables['temp0'][:]
                md.remd_types.append("T-REMD (temp0)")
                if len(temps) > 0:
                    md.remd_temp_stats = (float(np.min(temps)), float(np.max(temps)), float(np.mean(temps)))

            if 'remd_dimtype' in vars_keys:
                md.is_remd = True
                md.remd_types.append("Multi-D REMD")

        finally:
            ds.close()

    except Exception as e:
        md.warnings.append(f"NetCDF Error: {e}")

    return md

def _parse_ascii_trajectory(filepath: str) -> TrajectoryMetadata:
    md = TrajectoryMetadata(filename=filepath, file_format="ASCII")
    try:
        with open(filepath, 'r') as f:
            md.title = f.readline().strip()
        md.warnings.append("ASCII format: No detailed metadata (time, box, count) extractable without prmtop.")
    except Exception:
        md.warnings.append("File empty or unreadable.")
    return md

def parse_mdcrd(filepath: str) -> TrajectoryMetadata:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"{filepath} not found")
    
    fmt = _detect_format(filepath)
    if fmt == "NetCDF":
        return _parse_netcdf_trajectory(filepath)
    else:
        return _parse_ascii_trajectory(filepath)

# -------------------------------
# 5. Sequence Analysis (The Fix)
# -------------------------------

def analyze_sequence(metadatas: Sequence[TrajectoryMetadata]) -> str:
    """
    Checks continuity of trajectory files based on timestamps and calculated dt.
    """
    if not metadatas:
        return "No files."

    # Filter useful NetCDF files
    valid = [m for m in metadatas if m.file_format == "NetCDF" and m.has_time]
    
    if not valid:
        return "No NetCDF files with time data found to analyze sequence."

    # Sort by start time
    valid.sort(key=lambda x: x.time_start)

    lines = []
    lines.append(f"--- Sequence Analysis ({len(valid)} files) ---")
    
    total_frames = sum(m.n_frames for m in valid)
    
    # Calculate global span
    t_first = valid[0].time_start
    t_last = valid[-1].time_end
    
    # Analyze continuity
    gaps = 0
    bad_overlaps = 0
    
    # Track volume statistics across the whole run
    all_avg_vols = [m.volume_stats[2] for m in valid if m.volume_stats]
    
    for i in range(len(valid) - 1):
        curr = valid[i]
        next_f = valid[i+1]
        
        # Logic: Next Start should be approx Current End + Current DT
        # If Current DT is missing (1 frame file), try using Next DT, or assume standard 1.0/2.0
        
        dt_ref = curr.avg_dt if curr.avg_dt else (next_f.avg_dt if next_f.avg_dt else 1.0)
        
        expected_start = curr.time_end + dt_ref
        delta = next_f.time_start - expected_start
        
        # Tolerance: 10% of dt or 0.1ps, whichever is larger
        tol = max(0.1, dt_ref * 0.1)
        
        if abs(delta) > tol:
            gaps += 1
            lines.append(f"  [Gap/Overlap] {os.path.basename(curr.filename)} ends {curr.time_end:.2f} | "
                         f"{os.path.basename(next_f.filename)} starts {next_f.time_start:.2f} "
                         f"(Expected ~{expected_start:.2f}, Diff {delta:.2f})")

    total_ns = (t_last - t_first) / 1000.0
    
    lines.append(f"Total Frames:    {total_frames:,}")
    lines.append(f"Time Coverage:   {t_first:.2f} to {t_last:.2f} ps")
    lines.append(f"Total Duration:  {total_ns:.3f} ns")
    
    if gaps == 0:
        lines.append("Status: Continuous (No gaps detected)")
    else:
        lines.append(f"Status: Found {gaps} discontinuities (see above)")

    if all_avg_vols:
        global_avg_vol = sum(all_avg_vols) / len(all_avg_vols)
        lines.append(f"Global Avg Volume: {global_avg_vol:,.2f} Å³")

    return "\n".join(lines)

def summarize_single(md: TrajectoryMetadata) -> str:
    s = []
    fname = os.path.basename(md.filename)
    s.append(f"File: {fname} [{md.file_format}]")
    
    if md.file_format == "NetCDF":
        s.append(f"  Atoms:  {md.n_atoms:,}")
        s.append(f"  Frames: {md.n_frames:,}")
        
        if md.has_time:
            dt_str = f"{md.avg_dt:.3f}" if md.avg_dt else "?"
            s.append(f"  Time:   {md.time_start:.1f} -> {md.time_end:.1f} ps (dt={dt_str})")
        
        if md.has_box and md.volume_stats:
            vmin, vmax, vavg = md.volume_stats
            s.append(f"  Volume: {vavg:,.1f} Å³ (Range: {vmin:,.1f}-{vmax:,.1f}) [{md.box_type}]")
        
        if md.is_remd:
            info = ", ".join(md.remd_types)
            s.append(f"  REMD:   {info}")
            if md.remd_temp_stats:
                 tmin, tmax, tavg = md.remd_temp_stats
                 s.append(f"  Temp0:  Avg {tavg:.1f} K (Range {tmin:.1f}-{tmax:.1f} K)")
    else:
        s.append(f"  Info:   Legacy ASCII format")
    
    if md.warnings:
        for w in md.warnings:
            s.append(f"  [Warn] {w}")
    
    return "\n".join(s)

# -------------------------------
# 6. CLI
# -------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse AMBER mdcrd/nc files.")
    parser.add_argument("inputs", nargs='+', help="Input files")
    parser.add_argument("--sequence-only", action="store_true", help="Show only sequence summary")
    
    args = parser.parse_args()
    
    # Expand globs
    files = []
    for inp in args.inputs:
        matched = glob.glob(inp)
        if matched: files.extend(matched)
        else: files.append(inp)
    
    files = sorted(list(set(files)))
    
    print(f"--- Processing {len(files)} files ---\n")
    if not HAS_NETCDF:
        print("Warning: NetCDF libraries not found. Deep parsing disabled.")

    metas = []
    for f in files:
        try:
            md = parse_mdcrd(f)
            metas.append(md)
            if not args.sequence_only:
                print(summarize_single(md))
        except Exception as e:
            print(f"Error {f}: {e}")

    if len(metas) > 1:
        print("\n" + "="*40)
        print(analyze_sequence(metas))
        print("="*40)