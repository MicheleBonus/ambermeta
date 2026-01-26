from __future__ import annotations

import math
import re
import glob
import os
from dataclasses import dataclass, field
from typing import Dict, List, Any, Union, Optional, Sequence

# -------------------------------
# 1. Constants & Lookups
# -------------------------------

SIMULATION_TYPES = {
    0: "Molecular Dynamics (MD)",
    1: "Minimization",
    5: "Trajectory Analysis (minimization)",
    6: "MD (Energy/Gradient only)",
}

THERMOSTATS = {
    0: "Constant Energy (NVE)",
    1: "Berendsen",
    2: "Andersen",
    3: "Langevin Dynamics",
    5: "Adaptive Thermostat",
    9: "Optimized Isokinetic (OIN)",
    10: "Stochastic Isokinetic",
    11: "Bussi (Stochastic Berendsen)"
}

BAROSTATS = {
    0: "No Pressure Control",
    1: "Berendsen (Isotropic)",
    2: "Monte Carlo (Anisotropic if ntp=2)", # Or isotropic if ntp=1, context depends on barostat flag
}

# -------------------------------
# 2. Metadata Dataclasses
# -------------------------------

@dataclass
class WtScheduleEntry:
    """
    Represents a single &wt namelist entry (varying conditions).
    """
    quantity: str                     # TYPE keyword (TEMP0, REST, CUT, END, ...)
    istep1: Any = None
    istep2: Any = None
    value1: Any = None
    value2: Any = None
    iinc: Any = None
    imult: Any = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.quantity.upper() == "END"


@dataclass
class MdinMetadata:
    """
    Represents the configuration of a SINGLE mdin file.
    """
    filename: str
    title: str = "Unknown Title"
    
    # --- Protocol ---
    simulation_type: str = "MD"          # human-readable from imin
    length_steps: Union[int, str] = 0    # nstlim
    dt: Union[float, str] = 0.001        # dt (ps) - Default is 0.001 (Manual p.6)
    restart_flag: Union[int, str] = 0    # irest
    ensemble: str = "Unknown"            # NVE / NVT / NPT / ...
    stage_role: str = "Generic MD Stage" # heuristic description
    
    # --- Output ---
    energy_freq: Union[int, str] = 50    # ntpr - Default 50 (Manual p.3)
    coord_freq: Union[int, str] = 0      # ntwx - Default 0
    restart_freq: Union[int, str] = 0    # ntwr - Default nstlim
    traj_format: str = "NetCDF"          # ioutfm
    
    # --- Physics ---
    cutoff: Union[float, str] = 8.0      # cut - Default depends on igb (Manual p.24)
    temp_control: str = "NVE"            # ntt
    target_temp: Union[float, str] = 300.0 # temp0 - Default 300.0 (Manual p.8)
    press_control: str = "None"          # ntp
    pbc: str = "Vacuum"                  # ntb
    constraints: str = "None"            # ntc
    
    # --- Features ---
    implicit_solvent: str = "No"         # igb
    restraints_active: bool = False      # ntr
    nmr_options: bool = False            # nmropt
    qmmm_active: bool = False            # ifqnt
    has_temp_ramp: bool = False          # from &wt
    has_restraint_schedule: bool = False # REST/RESTS/RESTL in &wt
    has_cutoff_schedule: bool = False    # CUT in &wt
    uses_free_energy: bool = False       # icfe/infe/ifmbar
    uses_constant_pH: bool = False       # icnstph/iphmd
    uses_constant_redox: bool = False    # solve
    uses_gamd: bool = False              # igamd
    uses_remd: bool = False              # numexchg or REMD placeholders
    
    # --- Raw Content ---
    cntrl_parameters: Dict[str, Any] = field(default_factory=dict)
    additional_namelists: List[Dict[str, Any]] = field(default_factory=list)
    wt_schedules: List[WtScheduleEntry] = field(default_factory=list)
    restraint_definitions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

# -------------------------------
# 3. Helper Functions
# -------------------------------

def _clean_value(val: str) -> Any:
    """
    Converts string values to appropriate Python types.
    - Preserves shell variables (${var}, $(cmd)) as strings.
    - Handles Fortran booleans and D-notation floats.
    """
    val = val.strip().strip(",").strip('"').strip("'")
    
    if not val:
        return ""
    
    # Shell variables or command substitutions -> keep as string
    if "$" in val:
        return val
        
    # Fortran Booleans
    if val.lower() == ".true.":
        return True
    if val.lower() == ".false.":
        return False

    # Integers
    try:
        return int(val)
    except ValueError:
        pass

    # Floats (including Fortran D-notation)
    try:
        return float(val.replace("d", "e").replace("D", "E"))
    except ValueError:
        return val


def _parse_namelist_string(content: str) -> Dict[str, Any]:
    """
    Parses the internal content of a namelist string (e.g., "imin=1, ntx=5").
    Returns a dict with lowercase keys.
    """
    kv_pattern = re.compile(
        r"(?P<key>[a-zA-Z0-9_]+)\s*=\s*"
        r"(?P<value>"
        r"'(?:[^']|\\')*'"   # single-quoted strings
        r'|"(?:[^"]|\\")*"'  # double-quoted strings
        r"|\$\{[^}]+\}"      # ${var}
        r"|\$\([^)]+\)"      # $(cmd)
        r"|[^,/\s]+"         # bare tokens
        r")"
    )
    
    data: Dict[str, Any] = {}
    for match in kv_pattern.finditer(content):
        key = match.group("key").lower()
        value = match.group("value")
        data[key] = _clean_value(value)
    return data


def _as_int(val: Any) -> Optional[int]:
    try:
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, int):
            return int(val)
        if isinstance(val, float) and val.is_integer():
            return int(val)
        if isinstance(val, str) and val and "$" not in val:
            return int(float(val.replace("d", "e").replace("D", "E")))
    except (ValueError, TypeError):
        return None
    return None


def _as_float(val: Any) -> Optional[float]:
    try:
        result = None
        if isinstance(val, bool):
            result = float(val)
        elif isinstance(val, (int, float)):
            result = float(val)
        elif isinstance(val, str) and val and "$" not in val:
            result = float(val.replace("d", "e").replace("D", "E"))
        # Filter out NaN and Inf values
        if result is not None and (math.isnan(result) or math.isinf(result)):
            return None
        return result
    except (ValueError, TypeError):
        return None

# -------------------------------
# 4. Main Parser
# -------------------------------

def parse_mdin_file(filepath: str) -> MdinMetadata:
    """
    Parses a single AMBER mdin file into an MdinMetadata object.
    """
    with open(filepath, "r") as fh:
        lines = fh.readlines()
    
    md = MdinMetadata(filename=filepath)
    if not lines:
        return md

    # --- 1. Extract Title ---
    title_found = False
    start_index = 0
    
    for i, line in enumerate(lines):
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith(("#", "!")):
            continue  # comment
        if clean.startswith("&"):
            # Namelist starts immediately; no explicit title
            md.title = "Untitled"
            start_index = i
            title_found = True
            break
        else:
            md.title = clean
            start_index = i + 1
            title_found = True
            break

    if not title_found:
        return md

    # --- 2. Extract namelists and free-text sections ---
    content_lines = lines[start_index:]
    full_content = "".join(content_lines)

    # Strip comments to simplify namelist parsing
    full_stripped = re.sub(r"[!#].*?(\n|$)", "\n", full_content)

    namelist_re = re.compile(
        r"&(?P<name>[a-zA-Z0-9_]+)(?P<body>.*?)(?:/|&end)",
        re.DOTALL | re.IGNORECASE,
    )

    last_pos = 0
    wt_entries: List[WtScheduleEntry] = []

    for match in namelist_re.finditer(full_stripped):
        name = match.group("name").lower()
        body = match.group("body")
        params = _parse_namelist_string(body)
        params["_namelist"] = name

        if name == "cntrl":
            md.cntrl_parameters.update(params)
        else:
            if name == "wt":
                # Build WtScheduleEntry
                q = str(params.get("type", "")).strip().strip("'").strip('"')
                entry = WtScheduleEntry(
                    quantity=q.upper(),
                    istep1=params.get("istep1"),
                    istep2=params.get("istep2"),
                    value1=params.get("value1"),
                    value2=params.get("value2"),
                    iinc=params.get("iinc"),
                    imult=params.get("imult"),
                    raw=params,
                )
                wt_entries.append(entry)
            md.additional_namelists.append(params)

        last_pos = match.end()

    md.wt_schedules = wt_entries

    # --- 3. Extract restraint definitions / trailing text ---
    raw_tail = full_stripped[last_pos:]
    tail_lines = [l.strip() for l in raw_tail.splitlines() if l.strip()]

    md.restraint_definitions = [
        l for l in tail_lines
        if l.upper() not in ("END", "EOF") and not l.startswith("&")
    ]

    # --- 4. Interpret into higher-level metadata ---
    _interpret_parameters(md)

    return md

# -------------------------------
# 5. Interpretation / High-level Metadata
# -------------------------------

def _interpret_parameters(md: MdinMetadata) -> None:
    """
    Maps raw &cntrl dictionary (and &wt) to semantic fields in MdinMetadata.
    Applies AMBER Manual defaults where keys are missing.
    """
    c = md.cntrl_parameters

    # --- Protocol basics ---
    imin = c.get("imin", 0)
    imin_i = _as_int(imin)
    if imin_i is not None:
        md.simulation_type = SIMULATION_TYPES.get(imin_i, f"Unknown (imin={imin_i})")
    else:
        md.simulation_type = f"Variable (imin={imin})"

    md.length_steps = c.get("nstlim", 0)
    
    # Manual Page 6: Default dt = 0.001
    md.dt = c.get("dt", 0.001)
    
    md.restart_flag = c.get("irest", 0)

    # --- Output ---
    # Manual Page 3: Default ntpr = 50
    md.energy_freq = c.get("ntpr", 50)
    
    # Manual Page 4: Default ntwx = 0
    md.coord_freq = c.get("ntwx", 0)
    
    # Manual Page 3: Default ntwr = nstlim
    if "ntwr" in c:
        md.restart_freq = c["ntwr"]
    else:
        # If nstlim is a shell variable, restart_freq becomes that variable
        md.restart_freq = c.get("nstlim", 1)

    md.traj_format = "NetCDF" if str(c.get("ioutfm", 1)) == "1" else "ASCII"

    # --- Thermostat / Barostat / constraints ---
    ntt = c.get("ntt", 0)
    ntt_i = _as_int(ntt)
    if ntt_i is not None:
        md.temp_control = THERMOSTATS.get(ntt_i, f"Unknown (ntt={ntt_i})")
    else:
        md.temp_control = str(ntt)

    # Manual Page 8: Default temp0 = 300.0
    md.target_temp = c.get("temp0", 300.0)

    ntp = c.get("ntp", 0)
    igb = c.get("igb", 0)
    
    # Resolve NTB Default (Manual Page 24)
    # "ntb=0 when igb>0, ntb=2 when ntp>0, and ntb=1 otherwise"
    if "ntb" in c:
        ntb_val = c["ntb"]
    else:
        igb_i = _as_int(igb)
        ntp_i = _as_int(ntp)
        if igb_i is not None and igb_i > 0:
            ntb_val = 0
        elif ntp_i is not None and ntp_i > 0:
            ntb_val = 2
        else:
            ntb_val = 1

    ntb_i = _as_int(ntb_val)
    ntp_i = _as_int(ntp)

    # PBC description
    if ntb_i is None:
        md.pbc = f"Template/Variable (ntb={ntb_val})"
    else:
        if ntb_i == 0:
            md.pbc = "Vacuum / No PBC"
        elif ntb_i == 1:
            md.pbc = "PBC / Constant Volume"
        elif ntb_i >= 2:
            md.pbc = "PBC / Constant Pressure"
        else:
            md.pbc = f"Unknown (ntb={ntb_i})"

    # Pressure control description
    if ntp_i is not None and ntp_i > 0:
        barostat_type = _as_int(c.get("barostat", 1)) # Default 1 (Berendsen) Manual p.10
        
        # Refine description based on NTP value
        scaling_type = "Isotropic"
        if ntp_i == 2: scaling_type = "Anisotropic"
        if ntp_i == 3: scaling_type = "Semi-Isotropic"
        
        algo = "Berendsen"
        if barostat_type == 2: algo = "Monte Carlo"
        
        md.press_control = f"{algo} ({scaling_type})"
    else:
        md.press_control = "None"

    # Constraints
    ntc = c.get("ntc", 1)
    ntc_i = _as_int(ntc)
    if ntc_i == 1:
        md.constraints = "None"
    elif ntc_i == 2:
        md.constraints = "H-bonds"
    elif ntc_i == 3:
        md.constraints = "All bonds"
    else:
        md.constraints = str(ntc)

    # Cutoff Default Logic (Manual Page 24)
    # "When igb > 0, the default is 9999.0... When igb==0, the default is 8.0"
    if "cut" in c:
        md.cutoff = c["cut"]
    else:
        igb_i = _as_int(igb)
        if igb_i is not None and igb_i > 0:
            md.cutoff = 9999.0
        else:
            md.cutoff = 8.0

    # --- Solvent / advanced features ---
    if "igb" in c and str(c["igb"]) != "0":
        md.implicit_solvent = f"GB Model {c['igb']}"
        # In implicit solvent we effectively don't have a real PBC box
        md.pbc = "Implicit solvent (no periodic box)"

    if str(c.get("ntr", 0)) != "0":
        md.restraints_active = True

    if str(c.get("nmropt", 0)) != "0":
        md.nmr_options = True

    if str(c.get("ifqnt", 0)) != "0":
        md.qmmm_active = True

    # Free energy / constant pH / redox / GaMD
    if _as_int(c.get("icfe", 0)) == 1 or _as_int(c.get("infe", 0)) == 1 or _as_int(c.get("ifmbar", 0)) == 1:
        md.uses_free_energy = True

    if _as_int(c.get("icnstph", 0)) == 1 or _as_int(c.get("iphmd", 0)) == 1:
        md.uses_constant_pH = True

    if "solve" in c:
        md.uses_constant_redox = True

    if _as_int(c.get("igamd", 0)):
        md.uses_gamd = True

    if _as_int(c.get("numexchg", 0)):
        md.uses_remd = True

    # --- &wt schedules ---
    if md.wt_schedules:
        for entry in md.wt_schedules:
            q = entry.quantity.upper()
            if q == "TEMP0":
                md.has_temp_ramp = True
            elif q in {"REST", "RESTS", "RESTL", "NOESY", "SHIFTS"}:
                md.has_restraint_schedule = True
            elif q == "CUT":
                md.has_cutoff_schedule = True

    # --- Ensemble classification ---
    md.ensemble = _classify_ensemble(
        ntb=ntb_i,
        ntt=ntt_i,
        ntp=ntp_i,
        implicit=(md.implicit_solvent != "No"),
    )

    # --- Stage role heuristics ---
    md.stage_role = _classify_stage(md)

    # --- Sanity checks / warnings ---
    _populate_warnings(md)

def _classify_ensemble(
    ntb: Optional[int],
    ntt: Optional[int],
    ntp: Optional[int],
    implicit: bool,
) -> str:
    """
    Returns a compact description of the ensemble based on ntb/ntt/ntp.
    """
    if implicit:
        # Most implicit solvent runs are NVT with or without thermostat.
        if ntt is None or ntt == 0:
            return "Implicit-solvent NVE"
        else:
            return "Implicit-solvent NVT"

    if ntb is None:
        return "Unknown ensemble (template)"

    if ntb == 0:
        # No periodic box
        if ntt is None or ntt == 0:
            return "NVE (no PBC)"
        else:
            return "NVT (no PBC)"
    elif ntb == 1:
        # PBC constant volume
        if ntt is None or ntt == 0:
            return "NVE (PBC, constant volume)"
        else:
            return "NVT (PBC, constant volume)"
    else:
        # Constant pressure variants
        if ntt is None or ntt == 0:
            base = "NPH"
        else:
            base = "NPT"
        if ntp is None:
            return f"{base} (unknown barostat)"
        if ntp == 1:
            return f"{base} (isotropic)"
        elif ntp == 2:
            return f"{base} (anisotropic)"
        elif ntp == 3:
            return f"{base} (semi-isotropic)"
        else:
            return f"{base} (ntp={ntp})"


def _classify_stage(md: MdinMetadata) -> str:
    """
    Heuristic classification of the role of this mdin in a protocol:
    Minimization / Heating / Equilibration / Production / Generic.
    """
    title = (md.title or "").lower()
    c = md.cntrl_parameters

    imin_i = _as_int(c.get("imin", 0)) or 0
    ntr_i = _as_int(c.get("ntr", 0)) or 0
    nmropt_i = _as_int(c.get("nmropt", 0)) or 0  # noqa: F841 (maybe used later)

    nstlim_i = _as_int(c.get("nstlim", 0)) or 0
    dt_f = _as_float(c.get("dt", md.dt)) or 0.0
    total_ns: Optional[float] = None
    if nstlim_i > 0 and dt_f > 0:
        total_ns = nstlim_i * dt_f / 1000.0

    # 1) Explicit minimization flag wins
    if imin_i != 0 or "minim" in title or "energy minim" in title:
        return "Energy minimization"

    # 2) Look for explicit cues in the title
    if "heat" in title or "thermal" in title:
        return "Heating / thermalization"
    if "equil" in title or "nvt" in title or "npt equil" in title:
        # refine by restraints
        if ntr_i != 0:
            return f"Equilibration with positional restraints [{md.ensemble}]"
        else:
            return f"Equilibration [{md.ensemble}]"
    if "prod" in title or "production" in title:
        if ntr_i != 0:
            return f"Production with restraints [{md.ensemble}]"
        else:
            return f"Production [{md.ensemble}]"

    # 3) Fallback to numeric heuristics
    if total_ns is not None:
        if total_ns < 0.1:
            # very short - often test or finishing equilibration
            if ntr_i != 0:
                return f"Short restrained equilibration ({total_ns:.3f} ns)"
            else:
                return f"Short MD segment ({total_ns:.3f} ns)"
        elif total_ns <= 5.0:
            # Medium length: likely equilibration or short production
            if ntr_i != 0:
                return f"Equilibration with restraints ({total_ns:.3f} ns)"
            else:
                return f"Short production or equilibration ({total_ns:.3f} ns)"
        else:
            # Long: probably production
            if ntr_i != 0:
                return f"Long production run with restraints ({total_ns:.3f} ns)"
            else:
                return f"Production run ({total_ns:.3f} ns)"

    # 4) Default generic MD stage
    return f"Generic MD stage [{md.ensemble}]"


def _populate_warnings(md: MdinMetadata) -> None:
    """
    Adds simple sanity-check warnings to the metadata.
    """
    c = md.cntrl_parameters

    ntx = _as_int(c.get("ntx", 1))
    irest = _as_int(c.get("irest", 0))

    if irest == 1 and (ntx is not None and ntx not in (4, 5, 7)):
        md.warnings.append(
            f"irest=1 but ntx={ntx} (typical restart uses ntx=4,5, or 7)."
        )

    # Very large timestep check
    dt_f = _as_float(md.dt)
    if dt_f is not None and dt_f > 0.004:
        md.warnings.append(
            f"Unusually large timestep dt={dt_f} ps (check hydrogen mass repartitioning / constraints)."
        )

    # Positional restraints but ntr==0 in title cues
    if "restraint" in (md.title or "").lower() and not md.restraints_active:
        md.warnings.append(
            "Title mentions restraints but ntr=0 in &cntrl."
        )

# -------------------------------
# 6. Summarizers
# -------------------------------

def summarize_metadata(md: MdinMetadata) -> str:
    """
    Human-readable single-file summary.
    """
    lines: List[str] = []
    lines.append(f"File: {os.path.basename(md.filename)}")
    lines.append(f"Title: {md.title}")
    lines.append(f"Simulation type: {md.simulation_type}")
    lines.append(f"Stage role: {md.stage_role}")
    lines.append(f"Ensemble: {md.ensemble}")
    
    # Length / timing
    steps_str = f"{md.length_steps}"
    total_ns: Optional[float] = None
    steps_int = _as_int(md.length_steps)
    dt_f = _as_float(md.dt)
    if steps_int is not None and dt_f is not None and dt_f > 0:
        total_ns = steps_int * dt_f / 1000.0
        steps_str += f" steps  ({total_ns:.3f} ns, dt={dt_f} ps)"
    else:
        if isinstance(md.dt, str):
            steps_str += f" (dt={md.dt})"
    lines.append(f"Length: {steps_str}")
    
    # Conditions
    conds: List[str] = []
    conds.append(f"T={md.target_temp} K ({md.temp_control})")
    conds.append(f"Box/PBC: {md.pbc}")
    if md.press_control != "None":
        conds.append(f"Pressure control: {md.press_control}")
    conds.append(f"Cutoff: {md.cutoff} Å")
    conds.append(f"Constraints: {md.constraints}")
    lines.append("Conditions: " + "; ".join(conds))
    
    # Output frequencies
    out_parts = [
        f"E every {md.energy_freq} steps" if md.energy_freq else "E: off",
        f"coords every {md.coord_freq} steps" if md.coord_freq else "coords: off",
        f"restart every {md.restart_freq} steps" if md.restart_freq else "restart: default",
        f"traj format: {md.traj_format}",
    ]
    lines.append("Output: " + ", ".join(out_parts))
    
    # Features / advanced methods
    feats: List[str] = []
    if md.restraints_active:
        feats.append("positional restraints (ntr>0)")
    if md.nmr_options:
        feats.append("NMR / &wt options (nmropt>0)")
    if md.qmmm_active:
        feats.append("QM/MM (ifqnt>0)")
    if md.implicit_solvent != "No":
        feats.append(md.implicit_solvent)
    if md.has_temp_ramp:
        feats.append("TEMP0 schedule in &wt")
    if md.has_restraint_schedule:
        feats.append("restraint-weight schedule in &wt")
    if md.has_cutoff_schedule:
        feats.append("cutoff schedule in &wt")
    if md.uses_free_energy:
        feats.append("Free energy / TI / MBAR")
    if md.uses_constant_pH:
        feats.append("constant pH MD")
    if md.uses_constant_redox:
        feats.append("constant redox MD")
    if md.uses_gamd:
        feats.append("Gaussian Accelerated MD (GaMD)")
    if md.uses_remd:
        feats.append("Replica Exchange MD (REMD)")
    
    if feats:
        lines.append("Features: " + "; ".join(feats))
    
    # &wt schedules (compact view)
    wt_descs: List[str] = []
    for entry in md.wt_schedules:
        if entry.is_terminal:
            continue
        q = entry.quantity
        if q == "TEMP0":
            wt_descs.append(
                f"TEMP0: {entry.value1} -> {entry.value2} (steps {entry.istep1}–{entry.istep2 or 'end'})"
            )
        elif q in {"REST", "RESTS", "RESTL"}:
            wt_descs.append(
                f"REST: {entry.value1} -> {entry.value2} (steps {entry.istep1}–{entry.istep2 or 'end'})"
            )
        elif q == "CUT":
            wt_descs.append(
                f"CUT: {entry.value1} -> {entry.value2} (steps {entry.istep1}–{entry.istep2 or 'end'})"
            )
        else:
            # Generic
            wt_descs.append(
                f"{q}: {entry.value1} -> {entry.value2} (steps {entry.istep1}–{entry.istep2 or 'end'})"
            )
    if wt_descs:
        lines.append("&wt schedules: " + "; ".join(wt_descs))
    
    # Restraints free-text
    if md.restraint_definitions:
        lines.append(
            f"Restraints section: {len(md.restraint_definitions)} non-empty lines "
            f"(starts with: '{md.restraint_definitions[0]}')"
        )
    
    # Warnings
    if md.warnings:
        lines.append("Warnings:")
        for w in md.warnings:
            lines.append(f"  - {w}")
    
    return "\n".join(lines)

def summarize_protocol(metadatas: Sequence[MdinMetadata]) -> str:
    """
    Summarize a sequence of mdin stages as a single protocol.
    The order of `metadatas` is preserved and assumed to be chronological.
    """
    if not metadatas:
        return "No stages."
    
    lines: List[str] = []
    lines.append(f"Protocol summary ({len(metadatas)} stages):")
    
    total_ns: float = 0.0
    have_total_time = True
    
    for idx, md in enumerate(metadatas, 1):
        steps_int = _as_int(md.length_steps)
        dt_f = _as_float(md.dt)
        stage_ns: Optional[float] = None
        if steps_int is not None and dt_f is not None and dt_f > 0:
            stage_ns = steps_int * dt_f / 1000.0
            total_ns += stage_ns
        else:
            have_total_time = False
        
        label = os.path.basename(md.filename)
        time_str = f"{stage_ns:.3f} ns" if stage_ns is not None else "time: unknown"
        
        lines.append(
            f"  {idx}. {label}: {md.stage_role} "
            f"[{md.simulation_type}, {md.ensemble}, {time_str}]"
        )
    
    if have_total_time:
        lines.append(f"Total (assuming sequential execution): {total_ns:.3f} ns")
    
    # High-level feature flags across all stages
    feats = set()
    for md in metadatas:
        if md.uses_free_energy:
            feats.add("Free energy / TI")
        if md.uses_constant_pH:
            feats.add("constant pH MD")
        if md.uses_constant_redox:
            feats.add("constant redox MD")
        if md.uses_gamd:
            feats.add("GaMD")
        if md.uses_remd:
            feats.add("REMD")
        if md.qmmm_active:
            feats.add("QM/MM")
    
    if feats:
        lines.append("Global special methods: " + ", ".join(sorted(feats)))
    
    return "\n".join(lines)

# -------------------------------
# 7. CLI Entry Point
# -------------------------------

def _expand_inputs(paths: Sequence[str]) -> List[str]:
    """
    Expand potential glob patterns manually (for Windows compatibility).
    """
    expanded: List[str] = []
    for p in paths:
        matched = glob.glob(p)
        if matched:
            expanded.extend(matched)
        else:
            expanded.append(p)
    # Remove duplicates while preserving order
    seen = set()
    unique: List[str] = []
    for p in expanded:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Parse AMBER mdin files and summarize MD protocol."
    )
    parser.add_argument(
        "inputs", nargs="+", help="Input mdin files (supports globbing like '*.in')"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Show full raw &cntrl dictionary and restraints for each file",
    )
    parser.add_argument(
        "--protocol-only",
        action="store_true",
        help="Only print global protocol summary (if multiple files)",
    )
    
    args = parser.parse_args()
    
    files = _expand_inputs(args.inputs)
    print(f"--- Processing {len(files)} files ---\n")
    
    all_meta: List[MdinMetadata] = []
    for fpath in files:
        if not os.path.exists(fpath):
            print(f"Error: File '{fpath}' not found.\n")
            continue
        try:
            md = parse_mdin_file(fpath)
            all_meta.append(md)
            if not args.protocol_only:
                print(summarize_metadata(md))
                if args.details:
                    print("  Raw &cntrl:", md.cntrl_parameters)
                    if md.restraint_definitions:
                        print("  Restraints:")
                        for line in md.restraint_definitions:
                            print("   ", line)
                print("-" * 60)
        except (IOError, OSError, ValueError, UnicodeDecodeError) as exc:
            print(f"Failed to parse {fpath}: {exc}")
            print("-" * 60)
    
    if len(all_meta) > 1:
        print()
        print(summarize_protocol(all_meta))