from __future__ import annotations

import re
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Sequence, Set

# -------------------------------
# 1. Heuristics based on Amber Reference Manual (Part II)
# -------------------------------

# Water models (Section 3.6)
WATER_RESNAMES = {
    "WAT", "HOH", "SOL",             # Classic
    "TIP3", "TP3", "TIP3P",          # TIP3P variants
    "TIP4", "T4P", "TIP4P", "T4E",   # TIP4P variants
    "TIP5", "T5P", "TIP5P",          # TIP5P
    "SPC", "SPCE", "SPC/E",          # SPC variants
    "OPC", "OPC3", "OL3",            # Modern OPC models
    "POL3", "QSP", "F3C"             # Polarizable / Flexible
}

# Organic Solvents (Section 3.6)
ORGANIC_SOLVENT_RESNAMES = {
    "MEOH", "CHCL3", "NMA", "UREA", "ETH", "MOL"
}

# Protein Residues (ff19SB, ff14SB, etc.)
# Includes standard AA, protonation states (HIE, HID), and termini (N/C prefixes)
PROTEIN_RESNAMES = {
    # Standard
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    # Protonation / Capping / Special
    "HIE", "HID", "HIP", "CYX", "CYM", "ASH", "GLH", "LYN", "ARN",
    "ACE", "NME", "NHE", "NH2", "CH3", # Caps
    "CRO", "CR2", "CRF", "CRQ", "CH6"  # Fluorescent chromophores (Section 3.10)
}

# DNA Residues (OL15, bsc1)
# Standard DNA in Amber usually starts with D (DA, DC...) or just A, C, G, T in older/some formats
DNA_RESNAMES = {
    "DA", "DC", "DG", "DT", 
    "DA5", "DC5", "DG5", "DT5", # 5'
    "DA3", "DC3", "DG3", "DT3"  # 3'
}

# RNA Residues (OL3)
RNA_RESNAMES = {
    "A", "C", "G", "U", 
    "A5", "C5", "G5", "U5",
    "A3", "C3", "G3", "U3",
    "RA", "RC", "RG", "RU"      # Sometimes used to distinguish from DNA
}

# Lipid21 / Lipid17 Residues (Table 3.9 in Manual)
LIPID_TAILS = {
    "LAL", "MY", "PA", "SA", "OL", "ST", "AR", "DHA"
}
LIPID_HEADS = {
    "PC", "PE", "PS", "PGR", "PGS", "PH", "SPM"
}
LIPID_OTHER = {"CHL", "CHOL", "POPC", "POPE", "DOPC", "DPPC"} 

LIPID_RESNAMES = LIPID_TAILS | LIPID_HEADS | LIPID_OTHER

# Common Atomic Ions (Section 3.7)
ION_RESNAMES = {
    "Li+", "Na+", "K+", "Rb+", "Cs+",  # Monovalent Cations
    "F-", "Cl-", "Br-", "I-",          # Monovalent Anions
    "Mg+", "Mg2+", "Ca2+", "Zn2+",     # Divalent
    "Ba2+", "Sr2+", "Fe2+", "Mn2+",
    "Co2+", "Ni2+", "Cu2+", "Cd2+",
    "Fe3+", "Cr3+", "Al3+"             # Trivalent
}

# -------------------------------
# 2. Low-level prmtop parser
# -------------------------------

class PrmtopParseError(Exception):
    """Raised when parsing a prmtop file fails."""
    pass


_FORMAT_RE = re.compile(
    r"\(\s*(?P<count>\d+)\s*(?P<type>[aiefAIEF])\s*(?P<width>\d+)"
    r"(?:\.(?P<prec>\d+))?\s*\)"
)


def _parse_format(fmt: str) -> Tuple[int, str, int, Optional[int]]:
    """
    Parse an AMBER prmtop FORTRAN format string like '(20a4)', '(10I8)'.
    """
    fmt = fmt.strip()
    m = _FORMAT_RE.search(fmt)
    if not m:
        raise PrmtopParseError(f"Unsupported format: {fmt!r}")
    count = int(m.group("count"))
    type_code = m.group("type").upper()
    width = int(m.group("width"))
    prec = m.group("prec")
    return count, type_code, width, int(prec) if prec is not None else None


def _convert_field(token: str, type_code: str) -> Any:
    token = token.strip()
    if not token:
        # Return empty string for 'A' types so joins don't produce "None"
        if type_code == "A":
            return ""
        return None
        
    if type_code == "A":
        return token
    if type_code == "I":
        return int(token)
    if type_code in ("E", "F"):
        token = token.replace("D", "E").replace("d", "e")
        return float(token)
    raise PrmtopParseError(f"Unknown type code {type_code}")


class PrmtopFile:
    """
    Generic AMBER prmtop reader with memory optimization.
    """

    def __init__(self, filename: str, target_flags: Optional[Set[str]] = None):
        self.filename = filename
        self.target_flags = target_flags  # If None, parse everything
        self.sections: Dict[str, List[Any]] = {}
        self.version_stamp: Optional[str] = None
        self._parse()

    def get(self, flag: str, default: Optional[List[Any]] = None) -> Optional[List[Any]]:
        return self.sections.get(flag.upper(), default)

    def _parse(self) -> None:
        current_flag: Optional[str] = None
        format_desc: Optional[Tuple[int, str, int, Optional[int]]] = None
        buf: List[str] = []

        def flush_section():
            nonlocal current_flag, format_desc, buf
            if current_flag is None or format_desc is None:
                return

            if self.target_flags is not None and current_flag not in self.target_flags:
                current_flag = None
                buf = []
                return

            # Parse data
            count, tcode, width, _ = format_desc
            parsed: List[Any] = []
            
            for raw_line in buf:
                line = raw_line.rstrip("\n")
                # Parse fixed-width chunks
                for k in range(count):
                    start = k * width
                    end = start + width
                    if start >= len(line):
                        break
                    token = line[start:end]
                    try:
                        val = _convert_field(token, tcode)
                        parsed.append(val)
                    except ValueError:
                        parsed.append(None)
            
            self.sections[current_flag] = parsed
            
            # Reset
            current_flag = None
            format_desc = None
            buf = []

        with open(self.filename, "r") as fh:
            for line in fh:
                if line.startswith("%VERSION"):
                    parts = line.split("=")
                    if len(parts) > 1:
                        self.version_stamp = parts[1].split()[0]
                    continue

                if line.startswith("%FLAG"):
                    flush_section()
                    parts = line.split()
                    if len(parts) >= 2:
                        current_flag = parts[1].strip()
                    continue

                if line.startswith("%FORMAT"):
                    current_format_str = line.split("FORMAT", 1)[1].strip()
                    try:
                        format_desc = _parse_format(current_format_str)
                    except PrmtopParseError:
                        current_flag = None
                        format_desc = None
                    buf = []
                    continue

                if current_flag is not None:
                    if line.startswith("%COMMENT"):
                        continue
                    buf.append(line)

            flush_section()

# -------------------------------
# 3. High-level metadata
# -------------------------------

@dataclass
class PrmtopMetadata:
    filename: str
    version: Optional[str] = None
    title: Optional[str] = None
    force_field_type: Optional[str] = None
    force_field_features: List[str] = field(default_factory=list)

    # Dimensions
    natom: Optional[int] = None
    nres: Optional[int] = None
    nbond: Optional[int] = None
    
    # Chemistry
    total_mass: float = 0.0
    total_charge: float = 0.0
    is_neutral: bool = False
    
    # Box / Density
    box_dimensions: Optional[List[float]] = None 
    box_angles: Optional[List[float]] = None     
    box_volume: Optional[float] = None
    density: Optional[float] = None
    solvent_type: str = "Vacuum"
    simulation_category: str = "Vacuum"

    # Composition
    residue_composition: Dict[str, int] = field(default_factory=dict)
    
    # Solvent Pointers
    num_solvent_molecules: int = 0
    num_solute_residues: int = 0

    # Hydrogen mass repartitioning (HMR)
    hmr_active: Optional[bool] = None
    hmr_hydrogen_mass_range: Optional[Tuple[float, float]] = None
    hmr_hydrogen_mass_summary: Optional[str] = None


def _classify_simulation(md: PrmtopMetadata):
    """
    Analyzes residue composition to build a descriptive Simulation Category string.
    e.g. "Protein/DNA Complex in Explicit Water"
    """
    
    # 1. Identify Components present
    has_protein = False
    has_dna = False
    has_rna = False
    has_lipid = False
    has_water = False
    has_organic = False
    has_ions = False
    
    for res in md.residue_composition:
        # Check standard sets
        if res in PROTEIN_RESNAMES: has_protein = True
        elif res in DNA_RESNAMES: has_dna = True
        elif res in RNA_RESNAMES: has_rna = True
        elif res in LIPID_RESNAMES: has_lipid = True
        elif res in WATER_RESNAMES: has_water = True
        elif res in ORGANIC_SOLVENT_RESNAMES: has_organic = True
        elif res in ION_RESNAMES: has_ions = True
        
        # Check specific prefixes if exact match failed (e.g., NALA, CALA)
        # 4-char protein residues often start with N/C for termini
        elif len(res) == 4 and (res[1:] in PROTEIN_RESNAMES):
            has_protein = True

    # 2. Build Solute Description
    solutes = []
    if has_protein: solutes.append("Protein")
    if has_dna: solutes.append("DNA")
    if has_rna: solutes.append("RNA")
    if has_lipid: solutes.append("Lipid/Membrane")
    
    # If no major biomolecules found but we have other stuff (excluding water/ions)
    # calculate remainder
    known_solvents = WATER_RESNAMES | ORGANIC_SOLVENT_RESNAMES | ION_RESNAMES
    unknown_residues = [r for r in md.residue_composition if r not in known_solvents and not (has_protein or has_dna or has_rna or has_lipid)]
    if unknown_residues and not solutes:
        solutes.append("Small Molecule / Ligand")
    elif unknown_residues:
        solutes.append("Ligand")

    solute_str = " / ".join(solutes) if solutes else "Pure Solvent/Ions"

    # 3. Build Solvent Description
    solvent_context = ""
    if md.solvent_type == "Implicit Solvent":
        solvent_context = "in Implicit Solvent"
    elif md.solvent_type == "Vacuum":
        solvent_context = "in Vacuum"
    else:
        # Explicit
        if has_water and has_organic:
            solvent_context = "in Mixed Solvent (Water+Organic)"
        elif has_water:
            solvent_context = "in Explicit Water"
        elif has_organic:
            solvent_context = "in Organic Solvent"
        else:
            solvent_context = "in Explicit Solvent (Unknown)"

    # 4. Combine
    md.simulation_category = f"{solute_str} {solvent_context}"
    
    # Refine Category if Empty
    if md.simulation_category.strip() == "in Vacuum":
        md.simulation_category = "Empty/Unknown System in Vacuum"


def extract_prmtop_metadata(filepath: str) -> PrmtopMetadata:
    """
    Parses a prmtop file and returns a summary PrmtopMetadata object.
    """
    
    target_flags = {
        "TITLE", "CTITLE", "POINTERS", "ATOM_NAME", "CHARGE", "MASS", 
        "RESIDUE_LABEL", "RESIDUE_POINTER", "BOX_DIMENSIONS", "RADIUS_SET", 
        "SOLVENT_POINTERS", "ATOMIC_NUMBER", "FORCE_FIELD_TYPE", 
        "CMAP_COUNT", "IFBOX"
    }

    prmtop = PrmtopFile(filepath, target_flags=target_flags)
    
    md = PrmtopMetadata(filename=filepath, version=prmtop.version_stamp)

    # 1. Title & FF Type
    if "TITLE" in prmtop.sections:
        raw_title = prmtop.sections["TITLE"]
        md.title = "".join(str(x) for x in raw_title if x).strip()
        
    if "CTITLE" in prmtop.sections:
        raw_ctitle = prmtop.sections["CTITLE"]
        md.title = "".join(str(x) for x in raw_ctitle if x).strip()
        md.force_field_features.append("CHAMBER (CHARMM converted)")

    if "FORCE_FIELD_TYPE" in prmtop.sections:
        raw_fft = prmtop.sections["FORCE_FIELD_TYPE"]
        md.force_field_type = "".join(str(x) for x in raw_fft if x).strip()

    if "CMAP_COUNT" in prmtop.sections:
        md.force_field_features.append("CMAP Correction")

    # 2. Pointers
    pointers = prmtop.get("POINTERS")
    if pointers:
        md.natom = pointers[0]
        md.nres = pointers[11]
        md.nbond = pointers[12]

    # 3. Chemistry
    charges = prmtop.get("CHARGE")
    if charges:
        valid_charges = [c for c in charges if c is not None]
        if valid_charges:
            raw_sum = sum(valid_charges)
            md.total_charge = raw_sum / 18.2223
            # Threshold set to 1e-2 as requested
            md.is_neutral = abs(md.total_charge) < 1e-2

    masses = prmtop.get("MASS")
    if masses:
        valid_masses = [m for m in masses if m is not None]
        md.total_mass = sum(valid_masses)

    atomic_numbers = prmtop.get("ATOMIC_NUMBER")
    if masses and atomic_numbers:
        hydrogen_masses = []
        count = min(len(masses), len(atomic_numbers))
        for mass, atomic_number in zip(masses[:count], atomic_numbers[:count]):
            if atomic_number == 1 and mass is not None:
                hydrogen_masses.append(mass)

        if hydrogen_masses:
            min_mass = min(hydrogen_masses)
            max_mass = max(hydrogen_masses)
            md.hmr_hydrogen_mass_range = (min_mass, max_mass)
            md.hmr_hydrogen_mass_summary = (
                f"{min_mass:.3f}-{max_mass:.3f} amu across {len(hydrogen_masses)} H"
            )
            has_elevated = max_mass >= 1.5
            has_normal = min_mass <= 1.1
            hmr_by_threshold = max_mass >= 2.0
            redistributed = has_elevated and has_normal
            md.hmr_active = hmr_by_threshold or redistributed
        else:
            md.hmr_active = False

    # 4. Box & Density
    box_data = prmtop.get("BOX_DIMENSIONS")
    if box_data and len(box_data) >= 4:
        beta = box_data[0]
        dims = box_data[1:4]
        md.box_dimensions = dims
        md.box_angles = [90.0, beta, 90.0]
        md.box_volume = dims[0] * dims[1] * dims[2]
        
        if md.box_volume > 0:
            md.density = (md.total_mass / md.box_volume) * 1.66054
        
        if abs(beta - 90.0) > 0.01:
            md.force_field_features.append("Truncated Octahedron/Triclinic")
        else:
            md.force_field_features.append("Orthorhombic Box")
        md.solvent_type = "Explicit Solvent"
    elif prmtop.get("RADIUS_SET"):
        md.solvent_type = "Implicit Solvent"
        rs = prmtop.get("RADIUS_SET")
        if rs:
            radius_str = "".join(str(x) for x in rs if x).strip()
            md.force_field_features.append(f"GB Radii: {radius_str}")

    # 5. Composition (Residue counting)
    res_labels = prmtop.get("RESIDUE_LABEL")
    if res_labels:
        cleaned_labels = [str(x).strip() for x in res_labels if x]
        md.residue_composition = dict(Counter(cleaned_labels))
        
        # Check for ions for FF features list
        ion_count = 0
        for res, count in md.residue_composition.items():
            if res in ION_RESNAMES:
                ion_count += count
        if ion_count > 0:
            md.force_field_features.append(f"Contains Ions ({ion_count})")

    # 6. Solvent Pointers
    solv_ptr = prmtop.get("SOLVENT_POINTERS")
    if solv_ptr and len(solv_ptr) >= 3:
        md.num_solute_residues = solv_ptr[0]
        md.num_solvent_molecules = solv_ptr[2]

    # 7. Final Classification
    _classify_simulation(md)

    return md


def summarize_metadata(md: PrmtopMetadata) -> str:
    lines = []
    lines.append(f"--- AMBER System Metadata ---")
    lines.append(f"File: {md.filename} ({md.version or 'Unknown ver'})")
    lines.append(f"Title: {md.title or 'N/A'}")
    
    natom_str = f"{md.natom:,}" if md.natom is not None else "Unknown"
    nres_str = f"{md.nres:,}" if md.nres is not None else "Unknown"
    
    lines.append(f"\n[System Properties]")
    lines.append(f"  Atoms:    {natom_str}")
    lines.append(f"  Residues: {nres_str}")
    lines.append(f"  Mass:     {md.total_mass:,.2f} Da")
    lines.append(f"  Charge:   {md.total_charge:.4f} e ({'Neutral' if md.is_neutral else 'Charged'})")
    
    lines.append(f"\n[Simulation Environment]")
    lines.append(f"  Category: {md.simulation_category}")
    if md.box_dimensions:
        lines.append(f"  Dims:     {md.box_dimensions[0]:.2f} x {md.box_dimensions[1]:.2f} x {md.box_dimensions[2]:.2f} Å")
        lines.append(f"  Volume:   {md.box_volume:,.2f} Å³")
        if md.density:
            lines.append(f"  Density:  {md.density:.4f} g/cm³")

    lines.append(f"\n[Force Field]")
    if md.force_field_type:
        lines.append(f"  Type:     {md.force_field_type}")
    if md.force_field_features:
        lines.append(f"  Features: {', '.join(md.force_field_features)}")
    
    lines.append(f"\n[Composition Summary]")
    sorted_comp = sorted(md.residue_composition.items(), key=lambda x: x[1], reverse=True)
    
    for i, (res, count) in enumerate(sorted_comp):
        if i >= 50:
            lines.append(f"  ... and {len(sorted_comp) - 50} more residue types")
            break
        
        # Add context to residue names
        context = []
        if res in PROTEIN_RESNAMES or (len(res) == 4 and res[1:] in PROTEIN_RESNAMES): context.append("Protein")
        elif res in DNA_RESNAMES: context.append("DNA")
        elif res in RNA_RESNAMES: context.append("RNA")
        elif res in LIPID_RESNAMES: context.append("Lipid")
        elif res in WATER_RESNAMES: context.append("Water")
        elif res in ION_RESNAMES: context.append("Ion")
        elif res in ORGANIC_SOLVENT_RESNAMES: context.append("Solvent")
        
        context_str = f"({', '.join(context)})" if context else ""
        lines.append(f"  {res}: {count} {context_str}")

    return "\n".join(lines)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        try:
            md = extract_prmtop_metadata(sys.argv[1])
            print(summarize_metadata(md))
        except Exception as e:
            print(f"Error processing file: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Usage: python extract_prmtop.py <file.prmtop>")
