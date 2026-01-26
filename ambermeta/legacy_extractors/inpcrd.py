from __future__ import annotations

import os
import sys
import math
import glob
import struct
from dataclasses import dataclass, field
from typing import Optional, List, Union, Tuple

# -------------------------------
# 1. Dependency Management
# -------------------------------
# We try to import netcdf readers. NetCDF4 is preferred for AMBER, 
# but scipy.io.netcdf is a good standard fallback.

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
class InpcrdMetadata:
    """
    Represents metadata extracted from an AMBER inpcrd/restrt file.
    """
    filename: str
    file_format: str = "Unknown"  # "Formatted ASCII" or "NetCDF"

    # --- Identification ---
    title: str = "N/A"
    program: str = "Unknown"
    program_version: str = "Unknown"
    conventions: str = "Unknown"

    # --- Dimensions ---
    natoms: int = 0
    nres: Optional[int] = None # Only available in NetCDF usually

    @property
    def n_atoms(self) -> int:
        """Standardized atom count property for consistency across metadata classes."""
        return self.natoms
    
    # --- Simulation State ---
    time: Optional[float] = None # picoseconds
    has_coordinates: bool = False
    has_velocities: bool = False
    has_forces: bool = False
    
    # --- Periodic Box ---
    has_box: bool = False
    box_dimensions: Optional[List[float]] = None # [a, b, c]
    box_angles: Optional[List[float]] = None     # [alpha, beta, gamma]
    box_volume: Optional[float] = None           # Angstrom^3
    
    # --- Warnings ---
    warnings: List[str] = field(default_factory=list)

# -------------------------------
# 3. Helper Functions
# -------------------------------

def _calc_volume(lengths: List[float], angles: List[float]) -> float:
    """
    Calculate volume of a triclinic cell.
    lengths: [a, b, c]
    angles: [alpha, beta, gamma] (in degrees)
    """
    a, b, c = lengths
    alpha, beta, gamma = [math.radians(x) for x in angles]
    
    term = 1 - math.cos(alpha)**2 - math.cos(beta)**2 - math.cos(gamma)**2 + \
           2 * math.cos(alpha) * math.cos(beta) * math.cos(gamma)
    
    if term < 0:
        return 0.0 # Should not happen in valid physical simulations
        
    return a * b * c * math.sqrt(term)

def _detect_format(filepath: str) -> str:
    """
    Reads the first 4 bytes to determine if file is NetCDF or ASCII.
    NetCDF files start with 'CDF' (ASCII bytes 67 68 70).
    """
    with open(filepath, 'rb') as f:
        header = f.read(4)
        if header.startswith(b'CDF'):
            return "NetCDF"
    return "ASCII"

# -------------------------------
# 4. ASCII Parser
# -------------------------------

def _parse_ascii_inpcrd(filepath: str) -> InpcrdMetadata:
    """
    Parses standard AMBER formatted ASCII inpcrd/restrt files.
    """
    md = InpcrdMetadata(filename=filepath, file_format="Formatted ASCII")
    
    with open(filepath, 'r') as f:
        # Line 1: Title
        try:
            md.title = f.readline().strip()
        except UnicodeDecodeError:
             md.title = "Binary/Corrupted Header"
             md.warnings.append("Could not decode title line.")

        # Line 2: NATOM [TIME]
        # Format: (I5, 5E15.7) usually, but parsing by split is safer
        line2 = f.readline()
        if not line2:
            md.warnings.append("File is empty or truncated after title.")
            return md
            
        parts = line2.split()
        if not parts:
            md.warnings.append("Second line (NATOM) is empty.")
            return md
            
        try:
            md.natoms = int(parts[0])
            if len(parts) >= 2:
                # AMBER uses 12.7 floats, python float() handles 'E' and 'D' notation usually
                t_str = parts[1].replace('D', 'E').replace('d', 'e')
                md.time = float(t_str)
        except ValueError:
             md.warnings.append(f"Could not parse NATOM/TIME from line 2: '{line2.strip()}'")
             return md

    # Logic to detect Box and Velocities based on line counts.
    # Coordinates are 6 floats per line (Format 6F12.7).
    # Box is 1 line at the end (6 floats).
    # Velocities follow coordinates, same format.
    
    coords_per_line = 6
    # Calculate how many lines the coordinates occupy
    lines_per_structure = math.ceil((md.natoms * 3) / coords_per_line)
    
    # Count total lines in file (minus header)
    # Re-open to count efficiently
    with open(filepath, 'r') as f:
        # Subtract 2 for Title + Natom line
        line_count = sum(1 for _ in f) - 2

    if line_count < 0:
        md.warnings.append("File header exists but body is missing.")
        return md

    # Heuristic Logic
    # 1. Coords only: lines ~ lines_per_structure
    # 2. Coords + Box: lines ~ lines_per_structure + 1
    # 3. Coords + Vels: lines ~ 2 * lines_per_structure
    # 4. Coords + Vels + Box: lines ~ 2 * lines_per_structure + 1
    
    md.has_coordinates = True # Implied by inpcrd
    
    remainder_box = 0
    
    if line_count >= (2 * lines_per_structure):
        md.has_velocities = True
        remainder_box = line_count - (2 * lines_per_structure)
    elif line_count >= lines_per_structure:
        md.has_velocities = False
        remainder_box = line_count - lines_per_structure
    else:
        md.warnings.append(f"File too short. Expected at least {lines_per_structure} lines for {md.natoms} atoms, found {line_count}.")
        return md
        
    # Check for Box
    if remainder_box == 1:
        md.has_box = True
        _parse_ascii_box(md)
    elif remainder_box > 1:
        # Sometimes files have trailing newlines
        md.warnings.append(f"Unexpected trailing lines ({remainder_box}). Assuming Box exists at end.")
        md.has_box = True
        _parse_ascii_box(md)
    
    return md

def _parse_ascii_box(md: InpcrdMetadata):
    """
    Reads the very last line of the file to extract box info.
    """
    # Efficiently read last line
    try:
        with open(md.filename, 'rb') as f:
            f.seek(-100, 2) # Go to near end (100 bytes should cover 6*12 chars)
            last_chunk = f.read()
            lines = last_chunk.decode('utf-8', errors='ignore').strip().split('\n')
            if not lines:
                return
            box_line = lines[-1]

            parts = box_line.split()
            if len(parts) >= 3:
                vals = [float(x) for x in parts]
                md.box_dimensions = vals[0:3]
                if len(vals) >= 6:
                    md.box_angles = vals[3:6]
                else:
                    md.box_angles = [90.0, 90.0, 90.0] # Default if not specified (old formats)

                md.box_volume = _calc_volume(md.box_dimensions, md.box_angles)
    except (IOError, OSError, ValueError, IndexError) as e:
        md.warnings.append(f"Failed to parse ASCII box line: {e}")

# -------------------------------
# 5. NetCDF Parser
# -------------------------------

def _parse_netcdf_inpcrd(filepath: str) -> InpcrdMetadata:
    """
    Parses AMBER NetCDF Restart/Trajectory files.
    """
    md = InpcrdMetadata(filename=filepath, file_format="NetCDF")
    
    if not HAS_NETCDF:
        md.warnings.append(f"NetCDF detected but no library installed (netCDF4 or scipy). Cannot parse details.")
        return md

    try:
        # Use a context manager if available (scipy.io.netcdf supports it, netCDF4 supports it)
        if NETCDF_BACKEND == "netCDF4":
            ds = nc.Dataset(filepath, 'r')
        else:
            ds = nc.netcdf_file(filepath, 'r', mmap=False)

        try:
            # Global Attributes
            # Accessing attrs differs slightly between libs, but usually obj.attr works
            if hasattr(ds, 'title'):
                md.title = str(ds.title)
                # Decode bytes if scipy returns bytes
                if isinstance(md.title, bytes): md.title = md.title.decode('utf-8')
            
            if hasattr(ds, 'program'):
                md.program = str(ds.program)
                if isinstance(md.program, bytes): md.program = md.program.decode('utf-8')

            if hasattr(ds, 'programVersion'):
                md.program_version = str(ds.programVersion)
                if isinstance(md.program_version, bytes): md.program_version = md.program_version.decode('utf-8')
                
            if hasattr(ds, 'Conventions'):
                md.conventions = str(ds.Conventions)
                if isinstance(md.conventions, bytes): md.conventions = md.conventions.decode('utf-8')

            # Dimensions
            if 'atom' in ds.dimensions:
                # scipy uses .dimensions[name], netCDF4 uses .dimensions[name].size
                dim = ds.dimensions['atom']
                if isinstance(dim, int): md.natoms = dim
                elif hasattr(dim, 'size'): md.natoms = dim.size
                else: md.natoms = len(dim)

            # Variables
            vars_keys = ds.variables.keys()
            
            # Time
            if 'time' in vars_keys:
                t_var = ds.variables['time']
                # NetCDF variables are array-like. For restart, usually 1 value.
                # Copy to numpy or list to avoid keeping file open
                if t_var.shape:
                    md.time = float(t_var[:][-1]) # Take last frame if multiple
                else:
                    md.time = float(t_var.getValue()) 

            # Coords / Velocities
            if 'coordinates' in vars_keys:
                md.has_coordinates = True
            
            if 'velocities' in vars_keys:
                md.has_velocities = True
                
            if 'forces' in vars_keys:
                md.has_forces = True

            # Box
            if 'cell_lengths' in vars_keys:
                md.has_box = True
                # Take last frame
                lengths = ds.variables['cell_lengths'][:]
                if len(lengths.shape) > 1: lengths = lengths[-1]
                
                angles = [90.0, 90.0, 90.0]
                if 'cell_angles' in vars_keys:
                    ang_data = ds.variables['cell_angles'][:]
                    if len(ang_data.shape) > 1: ang_data = ang_data[-1]
                    angles = list(ang_data)
                
                md.box_dimensions = list(lengths)
                md.box_angles = angles
                md.box_volume = _calc_volume(md.box_dimensions, md.box_angles)

        finally:
            ds.close()

    except (IOError, OSError, ValueError, KeyError, IndexError, RuntimeError) as e:
        md.warnings.append(f"Error parsing NetCDF structure: {e}")

    return md

# -------------------------------
# 6. Main Entry Point & Summarizer
# -------------------------------

def parse_inpcrd(filepath: str) -> InpcrdMetadata:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File {filepath} not found.")
    
    fmt = _detect_format(filepath)
    if fmt == "NetCDF":
        return _parse_netcdf_inpcrd(filepath)
    else:
        return _parse_ascii_inpcrd(filepath)

def summarize_metadata(md: InpcrdMetadata) -> str:
    lines = []
    lines.append(f"File: {os.path.basename(md.filename)}")
    lines.append(f"Format: {md.file_format}")
    if md.file_format == "NetCDF":
        be_str = f" (via {NETCDF_BACKEND})" if HAS_NETCDF else " (Library missing)"
        lines[-1] += be_str
        lines.append(f"Conventions: {md.conventions}")
        lines.append(f"Program: {md.program} {md.program_version}")

    lines.append(f"Title: {md.title}")
    
    # System Info
    lines.append(f"Atoms: {md.natoms:,}")
    
    t_str = f"{md.time:.4f} ps" if md.time is not None else "N/A"
    lines.append(f"Time:  {t_str}")
    
    # Contents
    contents = []
    if md.has_coordinates: contents.append("Coordinates")
    if md.has_velocities: contents.append("Velocities")
    if md.has_forces: contents.append("Forces")
    lines.append(f"Contains: {', '.join(contents)}")
    
    # Box Info
    if md.has_box and md.box_dimensions:
        lines.append(f"Box Type: Periodic")
        a, b, c = md.box_dimensions
        al, be, ga = md.box_angles if md.box_angles else (90,90,90)
        lines.append(f"  Dimensions: {a:.4f}  {b:.4f}  {c:.4f} Å")
        lines.append(f"  Angles:     {al:.4f}  {be:.4f}  {ga:.4f} degrees")
        if md.box_volume:
            lines.append(f"  Volume:     {md.box_volume:,.2f} Å³")
    else:
        lines.append(f"Box Type: None (Vacuum / Infinite)")

    if md.warnings:
        lines.append("Warnings:")
        for w in md.warnings:
            lines.append(f"  - {w}")
            
    return "\n".join(lines)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Parse AMBER inpcrd/restrt files (ASCII or NetCDF).")
    parser.add_argument("inputs", nargs='+', help="Input files (supports globbing)")
    
    args = parser.parse_args()
    
    # Expand globs
    expanded_files = []
    for inp in args.inputs:
        matched = glob.glob(inp)
        if matched: expanded_files.extend(matched)
        else: expanded_files.append(inp)
    
    # Process
    print(f"--- Processing {len(expanded_files)} files ---")
    if HAS_NETCDF:
        print(f"NetCDF Backend: {NETCDF_BACKEND}")
    else:
        print("NetCDF Backend: Not found (NetCDF files will only be identified, not parsed)")
    print("")

    for fpath in expanded_files:
        try:
            md = parse_inpcrd(fpath)
            print(summarize_metadata(md))
            print("-" * 50)
        except (IOError, OSError, ValueError, FileNotFoundError) as e:
            print(f"Error reading {fpath}: {e}")
            print("-" * 50)