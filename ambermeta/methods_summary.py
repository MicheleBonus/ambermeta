"""The methods summary: a compact digest of `summary.json` for writing a Methods section.

`summary.json` (``SimulationProtocol.to_dict()``) is the exhaustive record: every file of
every run, parsed. It grows with the number of runs, to tens of megabytes for a campaign of
a few thousand. A Methods section needs the opposite shape: the protocol once, per phase,
with the settings stated once and the runs that differ named as exceptions. That is what
:func:`build_methods_summary` writes, from the summary dict alone, so it can be rebuilt from
any `summary.json` already on disk::

    python -m ambermeta.methods_summary summary.json -o methods_summary.json

The digest is lenient: it keeps whatever a Methods section might report, and states where
each interpreted value came from (``source``):

* ``mdin``: set explicitly in the mdin;
* ``mdout``: not set in the mdin; the value AMBER used, as its mdout echoes it (the AMBER
  default for that run);
* ``default``: stated by neither file; the documented AMBER default, filled in by
  AmberMeta;
* ``derived``: computed by AmberMeta from other values.

A summary written by an older AmberMeta lacks some of the fields this reads (per-run
replica tags, the mdout's CONTROL DATA settings, per-run simulated time, atoms per
residue). Every one of them degrades: the digest falls back to what the older file has and
says so in ``basis`` fields, and leaves out what cannot be recovered.

Pure: no file is read, nothing is written. The input is not modified.
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import sys
from collections import Counter, OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = ["SCHEMA_VERSION", "NOT_IN_RUN_FILES", "build_methods_summary",
           "dumps_methods_summary", "main"]

#: Version of the digest's layout. The per-run methods summary of AmberMeta 1.2 and
#: earlier had no version field; this layout replaces it.
SCHEMA_VERSION = "2.0"

#: What a Methods section needs that no AMBER run file records.
NOT_IN_RUN_FILES = [
    "force field names (protein, nucleic acid, lipid, carbohydrate) and ligand parameters",
    "water model name (the topology gives only the number of sites per water molecule)",
    "ion parameters and salt concentration (counter-ions and added salt look alike)",
    "how protonation states were assigned (the residue names give the states, not the method)",
    "system preparation: structure source, modeling of missing parts, solvation, ion placement",
    "analysis software and analysis protocol",
]

MAX_FINDINGS = 15
MAX_VALUES = 6          # distinct values listed per setting before "more_values"
MAX_NAMES = 5           # replica or run names listed per exception
MAX_SEQUENCE = 12       # values listed in a per-replica sequence
MAX_TOPOLOGIES = 5
MAX_OTHER_RESIDUES = 25
MAX_REPLICA_NAMES = 20

_SOURCES = OrderedDict([
    ("mdin", "set explicitly in the mdin"),
    ("mdout", "not set in the mdin; the value AMBER used, as echoed in the mdout "
              "(the AMBER default for that run)"),
    ("default", "stated by neither file; the documented AMBER default, filled in by "
                "AmberMeta"),
    ("derived", "computed by AmberMeta from other values"),
])

# AMBER's documented defaults, used only when neither the mdin nor the mdout states a value.
# Version-dependent ones (`ig`, `ioutfm`) are the current ones.
_DEFAULTS: Dict[str, Any] = {
    "imin": 0, "irest": 0, "ntx": 1, "ntb": 1, "igb": 0, "ntt": 0, "temp0": 300.0,
    "tempi": 0.0, "gamma_ln": 0.0, "tautp": 1.0, "ntp": 0, "barostat": 1, "pres0": 1.0,
    "comp": 44.6, "taup": 1.0, "mcbarint": 100, "cut": 8.0, "ntc": 1, "ntf": 1,
    "dt": 0.001, "nstlim": 1, "ntwx": 0, "ntpr": 50, "ioutfm": 1, "iwrap": 0, "ig": -1,
    "maxcyc": 1, "ncyc": 10, "ntmin": 1, "ntr": 0, "nmropt": 0, "use_pme": 1,
}

_THERMOSTATS = {0: "none (constant energy)", 1: "Berendsen weak coupling", 2: "Andersen",
                3: "Langevin", 9: "optimized isokinetic Nose-Hoover (OIN)",
                10: "stochastic isokinetic Nose-Hoover RESPA (SINR)",
                11: "Bussi stochastic velocity rescaling"}
_BAROSTATS = {1: "Berendsen", 2: "Monte Carlo"}
# The thermostat names the whole-file mdout parser stores, for summaries that predate
# `mdout_control`.
_LEGACY_THERMOSTATS = {"Constant Energy (NVE)": 0, "Berendsen": 1, "Andersen": 2,
                       "Langevin": 3, "Optimized Isokinetic": 9, "Stochastic Isokinetic": 10}
_PRESSURE_SCALING = {1: "isotropic", 2: "anisotropic", 3: "semi-isotropic",
                     4: "isotropic, z only"}
_CONSTRAINTS = {1: "none", 2: "SHAKE on bonds to hydrogen", 3: "SHAKE on all bonds"}
_MIN_METHODS = {0: "conjugate gradient", 1: "steepest descent, then conjugate gradient",
                2: "steepest descent", 3: "XMIN", 4: "LMOD"}
_SPECIAL = OrderedDict([
    ("uses_remd", ("replica exchange (REMD)", ("numexchg", "rem", "remd_dimension"))),
    ("uses_gamd", ("Gaussian accelerated MD (GaMD)",
                   ("igamd", "ie", "irest_gamd", "ntcmd", "nteb", "ntave", "ntcmdprep",
                    "ntebprep", "sigma0p", "sigma0d"))),
    ("uses_free_energy", ("alchemical free energy (TI/FEP)",
                          ("icfe", "ifsc", "clambda", "ifmbar", "timask1", "timask2",
                           "scmask1", "scmask2", "infe"))),
    ("uses_constant_pH", ("constant pH", ("icnstph", "solvph", "ntcnstph", "iphmd"))),
    ("uses_constant_redox", ("constant redox potential", ("icnste", "solve", "ntcnste"))),
    ("qmmm_active", ("QM/MM", ("ifqnt",))),
])

_AMINO = set(
    "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL "
    "HID HIE HIP HIN CYX CYM ASH GLH LYN ARN TYM SEP TPO PTR NLE".split())
_CAPS = {"ACE", "NME", "NHE", "NH2"}
_PROTEIN_VARIANTS = {"HIS", "HID", "HIE", "HIP", "HIN", "CYX", "CYM", "ASH", "GLH", "LYN",
                     "ARN", "TYM"}
_NUCLEIC = set(
    "DA DC DG DT DA5 DC5 DG5 DT5 DA3 DC3 DG3 DT3 DAN DCN DGN DTN "
    "A C G U A5 C5 G5 U5 A3 C3 G3 U3 AN CN GN UN RA RC RG RU RA5 RC5 RG5 RU5 RA3 RC3 RG3 "
    "RU3".split())


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _round(value: Any, digits: int = 4) -> Any:
    """A number rounded to `digits` significant figures; ints and non-numbers unchanged."""
    v = _num(value)
    if v is None or isinstance(v, int) or v == 0:
        return value
    magnitude = int(math.floor(math.log10(abs(v))))
    return round(v, max(0, digits - 1 - magnitude))


def _clean(value: Any) -> Any:
    """A setting value in one comparable form: whole floats from the mdin echo (`300`)
    and the mdout (`300.0`) must count as one value."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return float(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return _round(value, 6)
    return value


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _details(stage: Dict[str, Any], kind: str) -> Dict[str, Any]:
    return _dict(_dict(_dict(stage.get("files")).get(kind)).get("details"))


def _basename(path: Any) -> Optional[str]:
    if not isinstance(path, str) or not path:
        return None
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _natural(name: str) -> List[Any]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(name))]


def _compress(per_member: Dict[str, Any]) -> Any:
    """`{replica: value}` as one value when every replica holds it, else the mapping
    (capped)."""
    if not per_member:
        return None
    values = {_key(v) for v in per_member.values()}
    if len(values) == 1:
        return {"each": next(iter(per_member.values())), "replicas": len(per_member)}
    names = sorted(per_member, key=_natural)
    out: Dict[str, Any] = OrderedDict((n, per_member[n]) for n in names[:MAX_REPLICA_NAMES])
    if len(names) > MAX_REPLICA_NAMES:
        nums = [v for v in per_member.values() if _num(v) is not None]
        out["more_replicas"] = len(names) - MAX_REPLICA_NAMES
        if nums:
            out["range_over_all"] = [min(nums), max(nums)]
    return out


def _prune(value: Any) -> Any:
    """Drop None and empty containers, recursively; keep 0 and False."""
    if isinstance(value, dict):
        out = OrderedDict()
        for k, v in value.items():
            v = _prune(v)
            if v is None or (isinstance(v, (dict, list)) and not v):
                continue
            out[k] = v
        return out
    if isinstance(value, list):
        out_list = []
        for v in value:
            v = _prune(v)
            if v is None or (isinstance(v, (dict, list)) and not v):
                continue
            out_list.append(v)
        return out_list
    return value


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------

class _Run:
    """What the digest needs from one stage of `summary.json`."""

    def __init__(self, index: int, stage: Dict[str, Any]) -> None:
        self.index = index
        self.stage = stage
        self.name = str(stage.get("name") or f"run {index + 1}")
        self.role = stage.get("stage_role") or None
        self.phase = stage.get("phase") or None
        # The protocol group this run is described in; see `_assign_groups`.
        self.group = self.phase or self.role or "unassigned"
        self.lineage = stage.get("lineage") or None
        self.mdin = _details(stage, "mdin")
        self.mdout = _details(stage, "mdout")
        self.prmtop = _details(stage, "prmtop")
        self.inpcrd = _details(stage, "inpcrd")
        self.cntrl = {str(k).lower(): v for k, v in _dict(self.mdin.get("cntrl_parameters")).items()
                      if not str(k).startswith("_")}
        self.echo = self._echo()
        self.queued = stage.get("status") == "queued"
        self.has_output = bool(self.mdout)
        self.finished = bool(self.mdout.get("finished_properly"))

    def _echo(self) -> Dict[str, Any]:
        """The mdout's CONTROL DATA settings. Older summaries carry no `mdout_control`;
        for those, the few settings the whole-file mdout parser kept stand in."""
        control = _dict(self.stage.get("mdout_control"))
        if control:
            return {str(k).lower(): v for k, v in control.items()}
        out: Dict[str, Any] = {}
        md = self.mdout
        if not md:
            return out
        if _num(md.get("nstlim")):
            out["nstlim"] = md["nstlim"]
        if _num(md.get("cutoff")) and md.get("cutoff") != 999.0:
            out["cut"] = md["cutoff"]
        if md.get("run_type") == "Minimization":
            out["imin"] = 1
        if _num(md.get("target_temp")) and md.get("target_temp") > 0:
            out["temp0"] = md["target_temp"]
        if md.get("run_type") != "Minimization":
            ntt = _LEGACY_THERMOSTATS.get(md.get("thermostat"))
            if ntt is not None:
                out["ntt"] = ntt
            barostat = md.get("barostat")
            if barostat == "None":
                out["ntp"] = 0
            elif barostat in ("Berendsen", "Monte Carlo"):
                out["barostat"] = 1 if barostat == "Berendsen" else 2
                # Pressure is regulated, but the old record does not say how it is scaled.
                out["ntp"] = 1
                out["_ntp_unknown"] = True
        return out

    def get(self, key: str, default: bool = True) -> Tuple[Any, Optional[str]]:
        """`key`'s value and its source: the mdin if it set it, else the mdout echo,
        else AMBER's default (when `default`)."""
        if key in self.cntrl and self.cntrl[key] is not None:
            explicit = self.cntrl[key]
            echoed = self.echo.get(key)
            # The echo is what AMBER parsed the mdin's text into; prefer it when both are
            # numbers, so `300` and `300.0` and `3.0d2` agree.
            if _num(echoed) is not None and _num(explicit) is not None:
                return _clean(echoed), "mdin"
            return _clean(explicit), "mdin"
        if key in self.echo and self.echo[key] is not None:
            return _clean(self.echo[key]), "mdout"
        if default and self.mdin and key in _DEFAULTS:
            return _DEFAULTS[key], "default"
        return None, None

    def value(self, key: str) -> Any:
        return self.get(key)[0]

    @property
    def minimization(self) -> bool:
        imin = self.value("imin")
        return imin == 1 or self.mdout.get("run_type") == "Minimization"

    @property
    def dt_ps(self) -> Optional[float]:
        dt = _num(self.value("dt"))
        if dt and dt > 0:
            return dt
        return None

    @property
    def elapsed_ps(self) -> Tuple[Optional[float], str]:
        value = _num(self.stage.get("elapsed_ps"))
        if value is not None:
            return value, "measured"
        if self.finished and not self.minimization:
            nstlim, dt = _num(self.value("nstlim")), self.dt_ps
            if nstlim and dt:
                return nstlim * dt, "stated"
        return None, "none"

    def start_ps(self) -> Optional[float]:
        """The simulation clock at the start of this run, where the files say it."""
        if self.minimization:
            return None
        stated = _num(self.stage.get("start_time_ps"))
        if stated is not None:
            return stated
        if self.stage.get("inpcrd_written_by_this_run"):
            return None             # that file's clock is the run's end
        irest = self.value("irest")
        if irest == 1:
            return _num(self.inpcrd.get("time"))
        if irest == 0:
            t = _num(self.cntrl.get("t"))
            return t if t is not None else 0.0
        return None

    def end_ps(self) -> Optional[float]:
        stats = _dict(self.mdout.get("stats"))
        return _num(stats.get("time_end"))

    def stat_mean(self, name: str) -> Tuple[Optional[float], int]:
        stats = _dict(self.mdout.get("stats"))
        acc = _dict(stats.get(name))
        count = acc.get("count")
        mean = _num(acc.get("mean"))
        if not isinstance(count, int) or count <= 0 or mean is None:
            return None, 0
        return mean, count

    def file_path(self) -> Optional[str]:
        for kind in ("mdout", "mdin", "inpcrd"):
            entry = _dict(_dict(self.stage.get("files")).get(kind))
            path = entry.get("filename") or _dict(entry.get("details")).get("filename")
            if isinstance(path, str) and path:
                return path.replace("\\", "/")
        return None

    # -- settings -----------------------------------------------------------------

    def settings(self) -> "OrderedDict[str, Tuple[Any, Optional[str]]]":
        """This run's settings as `{name: (value, source)}`. A setting neither file
        states, on a run whose mdin was not read, is left out: the AMBER default applies
        to what an mdin omits, not to what nobody has seen."""
        s: "OrderedDict[str, Tuple[Any, Optional[str]]]" = OrderedDict()
        if not self.mdin and not self.echo:
            return s
        get = self.get

        def put(name: str, value: Any, source: Optional[str]) -> None:
            if value is not None:
                s[name] = (value, source)

        def put_key(name: str, key: str, default: bool = True) -> None:
            put(name, *get(key, default=default))

        igb, igb_src = get("igb")
        ntb, ntb_src = get("ntb")
        ntp, ntp_src = get("ntp")
        if ntb_src == "default":
            # AMBER's own rule: ntb follows ntp and igb when the mdin does not set it.
            ntb = 0 if (igb or 0) > 0 else (2 if (ntp or 0) > 0 else 1)
        if igb is not None and igb > 0:
            put("electrostatics", f"generalized Born implicit solvent (igb = {igb})", igb_src)
            put_key("implicit_solvent_salt_M", "saltcon", default=False)
        elif ntb is not None and ntb > 0:
            pme, pme_src = get("use_pme")
            if pme is not None:
                put("electrostatics", "particle mesh Ewald" if pme != 0
                    else "Ewald without PME (use_pme = 0)", pme_src)
        elif ntb == 0:
            put("electrostatics", "no periodic boundaries", ntb_src)
        put_key("nonbonded_cutoff_A", "cut")
        if self.minimization:
            put("run_type", "energy minimization", None)
            ntmin, ntmin_src = get("ntmin")
            if ntmin is not None:
                put("minimization_method", _MIN_METHODS.get(ntmin, f"ntmin = {ntmin}"),
                    ntmin_src)
            put_key("max_cycles", "maxcyc")
            if ntmin == 1:
                put_key("steepest_descent_cycles", "ncyc")
        else:
            put("run_type", "molecular dynamics", None)
            ntt, ntt_src = get("ntt")
            if ntt is not None and ntb is not None and not self.echo.get("_ntp_unknown"):
                put("ensemble", self._ensemble(ntb, ntp, ntt, igb), "derived")
            if ntt is not None:
                put("thermostat", _THERMOSTATS.get(ntt, f"ntt = {ntt}"), ntt_src)
            if ntt is not None and ntt > 0:
                put_key("target_temperature_K", "temp0")
                if ntt == 3:
                    put_key("collision_frequency_per_ps", "gamma_ln")
                elif ntt == 1:
                    put_key("temperature_coupling_time_ps", "tautp")
                elif ntt == 2:
                    put_key("andersen_randomization_steps", "vrand", default=False)
            irest, irest_src = get("irest")
            if irest == 1:
                put("start", "coordinates and velocities from a restart (irest = 1)",
                    irest_src)
            elif irest is not None:
                put("start", "new velocities (irest = 0)", irest_src)
                if ntt is not None and ntt > 0:
                    put_key("initial_temperature_K", "tempi")
            schedule = self._wt("TEMP0")
            if schedule:
                put("temperature_schedule", schedule, "mdin")
            if ntp is not None and ntp > 0:
                barostat, baro_src = get("barostat")
                if baro_src == "default" and "pres0" in self.echo:
                    # pmemd and sander print the barostat number only when the mdin sets
                    # it; the Monte Carlo barostat announces itself with `mcbarint`.
                    barostat, baro_src = (2 if "mcbarint" in self.echo else 1), "mdout"
                if barostat is not None:
                    put("barostat", _BAROSTATS.get(barostat, f"barostat = {barostat}"),
                        baro_src)
                if not self.echo.get("_ntp_unknown"):
                    put("pressure_scaling", _PRESSURE_SCALING.get(ntp, f"ntp = {ntp}"), ntp_src)
                put_key("target_pressure_bar", "pres0")
                if barostat == 2:
                    put_key("barostat_interval_steps", "mcbarint")
                elif barostat is not None:
                    put_key("pressure_relaxation_time_ps", "taup")
                    put_key("compressibility_1e-6_per_bar", "comp")
                csurften = get("csurften", default=False)
                if csurften[0]:
                    put("surface_tension_regulation", *csurften)
            elif ntp == 0:
                put("barostat", "none (constant volume)" if ntb == 1 else "none", ntp_src)
            dt, dt_src = get("dt")
            if _num(dt):
                put("time_step_fs", _round(dt * 1000.0, 6), dt_src)
            nstlim, nstlim_src = get("nstlim")
            put("steps_per_run", nstlim, nstlim_src)
            if _num(nstlim) and _num(dt):
                put("stated_run_length_ps", _round(nstlim * dt, 8), "derived")
            ntwx, ntwx_src = get("ntwx")
            if ntwx and _num(dt):
                put("frame_interval", {"steps": ntwx, "ps": _round(ntwx * dt, 8)}, ntwx_src)
            elif ntwx == 0:
                put("frame_interval", "no trajectory written (ntwx = 0)", ntwx_src)
            put_key("energy_interval_steps", "ntpr")
            put_key("restart_interval_steps", "ntwr", default=False)
            ioutfm, ioutfm_src = get("ioutfm")
            if ioutfm is not None:
                put("trajectory_format",
                    {0: "ASCII", 1: "NetCDF"}.get(ioutfm, f"ioutfm = {ioutfm}"), ioutfm_src)
            iwrap, iwrap_src = get("iwrap")
            if iwrap is not None:
                put("coordinate_wrapping", {0: "off", 1: "on (iwrap = 1)"}.get(iwrap, iwrap),
                    iwrap_src)
            ntc, ntc_src = get("ntc")
            if ntc is not None:
                put("constraints", _CONSTRAINTS.get(ntc, f"ntc = {ntc}"), ntc_src)
            # The SETTING, from the mdin alone: the mdout's `ig` is the seed AMBER
            # resolved, which differs per run under ig = -1 and is reported per phase as
            # `resolved_seeds`, not as a setting.
            if self.mdin:
                ig = _num(self.cntrl.get("ig"))
                if ig is None:
                    put("random_seed", "chosen by AMBER at run time (ig = -1)", "default")
                elif ig < 0:
                    put("random_seed", "chosen by AMBER at run time (ig = -1)", "mdin")
                else:
                    put("random_seed", f"fixed (ig = {int(ig)})", "mdin")
        ntr, ntr_src = get("ntr")
        if ntr == 1:
            mask = self.cntrl.get("restraintmask")
            weight = self.cntrl.get("restraint_wt", self.echo.get("restraint_wt"))
            put("positional_restraints",
                f"{_clean(weight) if weight is not None else '?'} kcal/mol/A^2 on "
                f"{mask if mask else 'an unstated mask'}", ntr_src)
            if self.mdin.get("restraint_definitions"):
                put("positional_restraints_group_input", "GROUP input after the namelists",
                    "mdin")
        elif ntr == 0:
            put("positional_restraints", "none", ntr_src)
        rest = self._wt("REST")
        if rest:
            put("restraint_weight_schedule", rest, "mdin")
        nmropt, nmropt_src = get("nmropt")
        if nmropt is not None and nmropt > 0:
            put("nmr_restraints_or_weight_changes", f"nmropt = {nmropt}", nmropt_src)
        special = self._special()
        if special:
            put("special_methods", special, "mdin")
        return s

    @staticmethod
    def _ensemble(ntb: Any, ntp: Any, ntt: Any, igb: Any) -> str:
        thermo = (ntt or 0) > 0
        if igb and igb > 0:
            return "implicit solvent, " + ("constant temperature" if thermo else "constant energy")
        if ntp and ntp > 0:
            return "NPT" if thermo else "NPH"
        if ntb and ntb > 0:
            return "NVT" if thermo else "NVE"
        return "non-periodic, " + ("constant temperature" if thermo else "constant energy")

    def _wt(self, prefix: str) -> List[str]:
        """The mdin's `&wt` entries of one type, one short line each: a schedule is read
        as a whole, and nested objects for it made up most of a large project's digest."""
        out = []
        for entry in self.mdin.get("wt_schedules") or []:
            if not isinstance(entry, dict):
                continue
            quantity = str(entry.get("quantity") or "").upper()
            if not quantity.startswith(prefix):
                continue
            out.append(f"{quantity} {_clean(entry.get('value1'))} -> "
                       f"{_clean(entry.get('value2'))} over steps {entry.get('istep1')}-"
                       f"{entry.get('istep2')}")
        return out

    def _special(self) -> Dict[str, Any]:
        out: Dict[str, Any] = OrderedDict()
        for flag, (label, keys) in _SPECIAL.items():
            if self.mdin.get(flag):
                params = OrderedDict((k, _clean(self.cntrl[k])) for k in keys if k in self.cntrl)
                out[label] = params or True
        return out


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _source_label(sources: Counter) -> Any:
    sources = Counter({k: v for k, v in sources.items() if k})
    if not sources:
        return None
    if len(sources) == 1:
        return next(iter(sources))
    return ", ".join(f"{k} ({n} runs)" for k, n in sources.most_common())


def _aggregate(key: str, entries: List[Tuple["_Run", Any, Optional[str]]],
               total_runs: int, multi: bool) -> Dict[str, Any]:
    """One setting over the runs of a phase: the common value once, the others as
    exceptions with their run counts, and the replicas holding them."""
    groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for run, value, source in entries:
        k = _key(value)
        g = groups.setdefault(k, {"value": value, "runs": 0, "sources": Counter(),
                                  "replicas": set(), "first": run.name})
        g["runs"] += 1
        g["sources"][source] += 1
        if run.lineage:
            g["replicas"].add(run.lineage)
    ordered = sorted(groups.values(), key=lambda g: -g["runs"])
    top = ordered[0]
    out: Dict[str, Any] = OrderedDict([("value", top["value"]),
                                       ("source", _source_label(top["sources"]))])
    if len(ordered) > 1 or top["runs"] != total_runs:
        out["runs"] = top["runs"]
    others = []
    for g in ordered[1:MAX_VALUES]:
        other: Dict[str, Any] = OrderedDict([("value", g["value"]), ("runs", g["runs"])])
        src = _source_label(g["sources"])
        if src != out["source"]:
            other["source"] = src
        if multi and g["replicas"]:
            names = sorted(g["replicas"], key=_natural)
            other["replicas"] = names[:MAX_NAMES] + (
                [f"... {len(names) - MAX_NAMES} more"] if len(names) > MAX_NAMES else [])
        else:
            other["example_run"] = g["first"]
        others.append(other)
    if others:
        out["other_values"] = others
    if len(ordered) > MAX_VALUES:
        out["more_values"] = len(ordered) - MAX_VALUES
    return out


def _sequence(runs: List["_Run"], key: str, per_run: Dict[int, Dict[str, Any]]) -> List[Any]:
    """The values `key` steps through, in run order, within the first replica (or the
    shared runs), consecutive repeats collapsed. Empty when it never changes."""
    order: List[Any] = []
    lineage = runs[0].lineage if runs else None
    for run in runs:
        if run.lineage != lineage or key not in per_run.get(run.index, {}):
            continue
        value = per_run[run.index][key][0]
        if not order or _key(order[-1]) != _key(value):
            order.append(value)
    if len(order) < 2:
        return []
    if len(order) > MAX_SEQUENCE:
        return order[:MAX_SEQUENCE] + [f"... {len(order) - MAX_SEQUENCE} more"]
    return order


def _range(values: Sequence[float], digits: int) -> Any:
    if not values:
        return None
    lo, hi = min(values), max(values)
    if _round(lo, digits) == _round(hi, digits):
        return _round(lo, digits)
    return [_round(lo, digits), _round(hi, digits)]


def _observed(runs: List["_Run"]) -> Dict[str, Any]:
    out: Dict[str, Any] = OrderedDict()
    for label, name, digits in (("temperature_K", "_temps", 4), ("pressure_bar", "_pressures", 3),
                                ("density_g_cm3", "_densities", 4)):
        means, weights = [], []
        for run in runs:
            mean, count = run.stat_mean(name)
            if mean is not None:
                means.append(mean)
                weights.append(count)
        if not means:
            continue
        overall = sum(m * w for m, w in zip(means, weights)) / sum(weights)
        entry = OrderedDict([("mean", _round(overall, digits)),
                             ("range_of_run_means", _range(means, digits))])
        if len(means) != len(runs):
            entry["runs"] = len(means)
        out[label] = entry
    if out:
        out["basis"] = "energies printed in the mdout files"
    return out


def _ns_per_day(runs: List["_Run"]) -> Any:
    values = [run.mdout.get("ns_per_day") for run in runs]
    values = [v for v in values if _num(v) and v > 0]
    if not values:
        return None
    return OrderedDict([("median", _round(statistics.median(values), 3)),
                        ("range", _range(values, 3))])


_NUMBERED_PHASE = re.compile(r"^(.*\S) (\d+)$")


def _assign_groups(runs: List["_Run"]) -> None:
    """Set each run's protocol group: its document phase, with the numbered repeats of a
    phase folded into it.

    ``discover`` numbers the repeated phases of a protocol that alternates roles --
    "Equilibration", "Production", "Equilibration 2", "Production 2", ... -- so the
    manifest can tell them apart. Described phase by phase, a campaign of 200 segments
    would be 400 entries saying the same thing; the digest describes the equilibration runs
    once and the production runs once, as it did when those phases shared one name. A name
    is folded only into a phase of the same role that the document also holds under the
    bare name, so phases a user named "NVT 1" and "NVT 2" stay apart.
    """
    roles: Dict[str, Counter] = {}
    for r in runs:
        if r.phase:
            roles.setdefault(r.phase, Counter())[r.role] += 1

    def role_of(name: str) -> Any:
        return roles[name].most_common(1)[0][0]

    for r in runs:
        if not r.phase:
            continue
        match = _NUMBERED_PHASE.match(r.phase)
        if (match and int(match.group(2)) >= 2 and match.group(1) in roles
                and role_of(match.group(1)) == role_of(r.phase)):
            r.group = match.group(1)


def _phase(name: str, runs: List["_Run"], multi: bool) -> Dict[str, Any]:
    roles = Counter(r.role for r in runs)
    role = roles.most_common(1)[0][0] if roles else None
    queued = [r for r in runs if r.queued]
    with_output = [r for r in runs if r.has_output]
    # Settings over the runs that ran; a phase that has not run yet is described by what
    # its mdins ask for.
    basis = with_output or runs
    per_run = {r.index: r.settings() for r in basis}
    keys: List[str] = []
    for r in basis:
        for k in per_run[r.index]:
            if k not in keys:
                keys.append(k)
    settings: Dict[str, Any] = OrderedDict()
    for k in keys:
        entries = [(r, per_run[r.index][k][0], per_run[r.index][k][1])
                   for r in basis if k in per_run[r.index]]
        agg = _aggregate(k, entries, len(basis), multi)
        seq = _sequence(basis, k, per_run)
        if seq:
            # A value the sequence already shows is not repeated as an "other value".
            shown = {_key(v) for v in seq}
            others = [o for o in agg.get("other_values", []) if _key(o["value"]) not in shown]
            if others:
                agg["other_values"] = others
            else:
                agg.pop("other_values", None)
            agg["sequence_in_run_order"] = seq
        settings[k] = agg

    lineages = sorted({r.lineage for r in runs if r.lineage}, key=_natural)
    out: Dict[str, Any] = OrderedDict()
    out["name"] = name
    out["role"] = role
    document_phases = OrderedDict((r.phase, None) for r in runs if r.phase)
    if len(document_phases) > 1:
        # Numbered repeats folded into this entry (see `_assign_groups`): the protocol
        # returns to this phase that many times.
        out["document_phases"] = len(document_phases)
    out["runs"] = len(runs)
    out["runs_with_output"] = len(with_output)
    out["finished_runs"] = sum(1 for r in runs if r.finished)
    if queued:
        out["queued_runs"] = len(queued)
    missing = len(runs) - len(with_output) - len(queued)
    if missing:
        out["runs_without_mdout"] = missing
    if multi:
        out["replicas"] = len(lineages)
        shared = sum(1 for r in runs if not r.lineage)
        if shared:
            out["shared_runs"] = shared
        if lineages:
            counts: Dict[str, int] = Counter(r.lineage for r in runs if r.lineage)
            out["runs_per_replica"] = _compress(dict(counts))
    out["first_run"] = runs[0].name
    if len(runs) > 1:
        out["last_run"] = runs[-1].name

    times = [(r, *r.elapsed_ps) for r in runs]
    measured = [(r, t) for r, t, basis_ in times if t is not None]
    if measured and not all(r.minimization for r in runs):
        total = 0.0
        for _, t in measured:
            total += t
        out["simulated_time_ns"] = _round(total / 1000.0, 6)
        kinds = {b for _, t, b in times if t is not None}
        out["simulated_time_basis"] = (
            None if kinds == {"measured"} else
            "stated length (nstlim x dt) of the runs that finished; this summary.json "
            "predates per-run measured times" if kinds == {"stated"} else
            "measured where available, otherwise the stated length of finished runs")
        if multi and lineages:
            per: Dict[str, float] = {}
            for r, t in measured:
                if r.lineage:
                    per[r.lineage] = per.get(r.lineage, 0.0) + t
            out["simulated_time_ns_per_replica"] = _compress(
                {k: _round(v / 1000.0, 6) for k, v in per.items()})

    starts: Dict[Any, float] = {}
    ends: Dict[Any, float] = {}
    for r in runs:
        member = r.lineage
        if member not in starts:
            start = r.start_ps()
            if start is not None:
                starts[member] = start
        end = r.end_ps()
        if end is not None:
            ends[member] = end
    if starts or ends:
        out["clock_ps"] = OrderedDict([
            ("first_run_starts_at", _range(list(starts.values()), 7)),
            ("last_frame_printed_at", _range(list(ends.values()), 7)),
        ])
    out["settings"] = settings
    seeds = [r.echo.get("ig") for r in basis if isinstance(r.echo.get("ig"), int)
             and not r.minimization]
    if seeds:
        out["resolved_seeds"] = OrderedDict([
            ("runs_with_a_seed_in_the_mdout", len(seeds)),
            ("distinct", len(set(seeds))),
        ])
    observed = _observed([r for r in runs if not r.minimization])
    if observed:
        out["observed"] = observed
    perf = _ns_per_day([r for r in runs if not r.minimization])
    if perf:
        out["performance_ns_per_day"] = perf
    return out


# ---------------------------------------------------------------------------
# Project-level blocks
# ---------------------------------------------------------------------------

_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+at\s+(\d{1,2}:\d{2}:\d{2}))?")


def _date(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None
    m = _DATE.search(text)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _software(runs: List["_Run"]) -> Dict[str, Any]:
    programs: Counter = Counter()
    gpus: Counter = Counter()
    no_gpu = 0
    dates: List[str] = []
    wall = 0.0
    for r in runs:
        md = r.mdout
        if not md:
            continue
        program = md.get("program")
        version = md.get("version")
        if program:
            label = (program, version if version and version != "Unknown" else None)
            programs[label] += 1
        gpu = md.get("gpu_model")
        if gpu and gpu != "None":
            gpus[gpu] += 1
        else:
            no_gpu += 1
        d = _date(md.get("run_date"))
        if d:
            dates.append(d)
        if _num(md.get("wall_time_seconds")):
            wall += md["wall_time_seconds"]
    out: Dict[str, Any] = OrderedDict()
    out["md_engine"] = [OrderedDict([("program", p), ("version", v), ("runs", n)])
                        for (p, v), n in programs.most_common()]
    if programs:
        out["md_engine_note"] = ("program and version from the mdout banner; an mdout "
                                 "without the PMEMD banner is reported as SANDER")
    out["gpus"] = [OrderedDict([("model", g), ("runs", n)]) for g, n in gpus.most_common()]
    if no_gpu and gpus:
        out["runs_without_a_gpu_recorded"] = no_gpu
    if dates:
        out["run_dates"] = OrderedDict([("first", min(dates)), ("last", max(dates)),
                                        ("runs_with_a_date", len(dates))])
    if wall:
        out["wall_time_hours"] = _round(wall / 3600.0, 4)
    return out


def _residue_class(name: str) -> str:
    upper = name.upper()
    if upper in _CAPS:
        return "cap"
    if upper in _AMINO or (len(upper) == 4 and upper[0] in "NC" and upper[1:] in _AMINO):
        return "protein"
    if name in _NUCLEIC or upper in _NUCLEIC:
        return "nucleic"
    from ambermeta.legacy_extractors.prmtop import (
        ION_RESNAMES, LIPID_RESNAMES, WATER_RESNAMES)
    if name in WATER_RESNAMES or upper in WATER_RESNAMES:
        return "water"
    if name in ION_RESNAMES:
        return "ion"
    if upper in LIPID_RESNAMES:
        return "lipid"
    return "other"


def _box(dims: Any, angles: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(dims, list) or len(dims) < 3 or not all(_num(d) for d in dims[:3]):
        return None
    out: Dict[str, Any] = OrderedDict([("edges_A", [round(d, 2) for d in dims[:3]])])
    if isinstance(angles, list) and len(angles) >= 3 and all(_num(a) for a in angles[:3]):
        out["angles_deg"] = [round(a, 2) for a in angles[:3]]
        if all(abs(a - 90.0) < 0.01 for a in angles[:3]):
            out["shape"] = "rectangular"
        elif all(abs(a - 109.4712) < 0.05 for a in angles[:3]):
            out["shape"] = "truncated octahedron"
        else:
            out["shape"] = "triclinic"
    return out


def _system(runs: List["_Run"]) -> Dict[str, Any]:
    groups: "OrderedDict[Tuple[Any, Any], List[_Run]]" = OrderedDict()
    for r in runs:
        if not r.prmtop:
            continue
        key = (_basename(r.prmtop.get("filename")), r.prmtop.get("natom"))
        groups.setdefault(key, []).append(r)
    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    topologies = []
    for (fname, natom), members in ranked[:MAX_TOPOLOGIES]:
        topologies.append(_topology(fname, natom, members, len(ranked) > 1))
    out: Dict[str, Any] = OrderedDict([("topologies", topologies)])
    if len(ranked) > MAX_TOPOLOGIES:
        out["more_topologies"] = len(ranked) - MAX_TOPOLOGIES
    no_topology = sum(1 for r in runs if not r.prmtop)
    if no_topology:
        out["runs_without_a_topology"] = no_topology
    return out


def _topology(fname: Any, natom: Any, runs: List["_Run"], several: bool) -> Dict[str, Any]:
    p = runs[0].prmtop
    comp = {str(k): v for k, v in _dict(p.get("residue_composition")).items()
            if isinstance(v, int)}
    sizes = {str(k): v for k, v in _dict(p.get("residue_atom_counts")).items()}
    classes: Dict[str, Dict[str, int]] = {}
    for name, count in comp.items():
        classes.setdefault(_residue_class(name), {})[name] = count
    out: Dict[str, Any] = OrderedDict()
    out["file"] = fname
    out["atoms"] = natom
    out["residues"] = p.get("nres")
    if several:
        out["runs"] = len(runs)
        out["phases"] = sorted({r.group for r in runs})
    residues: Dict[str, Any] = OrderedDict()
    protein = classes.get("protein", {})
    if protein:
        variants = {k: v for k, v in protein.items()
                    if k.upper() in _PROTEIN_VARIANTS or k.upper()[1:] in _PROTEIN_VARIANTS}
        residues["protein"] = OrderedDict([
            ("residues", sum(protein.values())),
            ("caps", classes.get("cap")),
            ("histidine_cysteine_and_protonation_variants",
             OrderedDict(sorted(variants.items())) or None),
        ])
    elif classes.get("cap"):
        residues["caps"] = classes["cap"]
    nucleic = classes.get("nucleic", {})
    if nucleic:
        residues["nucleic_acid"] = OrderedDict([("residues", sum(nucleic.values())),
                                                ("by_name", OrderedDict(sorted(nucleic.items())))])
    if classes.get("lipid"):
        residues["lipids"] = OrderedDict(sorted(classes["lipid"].items(),
                                                key=lambda kv: -kv[1]))
    water = classes.get("water", {})
    if water:
        entry: Dict[str, Any] = OrderedDict([("molecules", sum(water.values())),
                                             ("residue_names", sorted(water))])
        sites = {sizes[n] for n in water if isinstance(sizes.get(n), int)}
        if len(sites) == 1:
            n_sites = sites.pop()
            entry["atoms_per_molecule"] = n_sites
            entry["model_hint"] = (f"{n_sites}-point water model; the topology does not "
                                   "name the model")
        out_water = entry
        residues["water"] = out_water
    if classes.get("ion"):
        residues["ions"] = OrderedDict(sorted(classes["ion"].items(), key=lambda kv: -kv[1]))
    other = classes.get("other", {})
    if other:
        ranked = sorted(other.items(), key=lambda kv: (-kv[1], kv[0]))
        listed: Dict[str, Any] = OrderedDict()
        for name, count in ranked[:MAX_OTHER_RESIDUES]:
            if isinstance(sizes.get(name), int):
                listed[name] = OrderedDict([("count", count), ("atoms", sizes[name])])
            else:
                listed[name] = count
        residues["other"] = listed
        if len(ranked) > MAX_OTHER_RESIDUES:
            residues["more_other_residue_names"] = len(ranked) - MAX_OTHER_RESIDUES
        residues["other_note"] = ("residue names outside the protein, nucleic-acid, lipid, "
                                  "water and ion sets: ligands, glycans, modified residues")
    out["residues_by_class"] = residues
    charge = _num(p.get("total_charge"))
    if charge is not None:
        out["net_charge_e"] = round(charge, 3)
    # The box of the first coordinates a run read; a restart the run itself wrote (the
    # scan path files it in the input slot) only when no run states what it read.
    box = None
    for own in (False, True):
        for run in runs:
            if bool(run.stage.get("inpcrd_written_by_this_run")) != own:
                continue
            box = _box(run.inpcrd.get("box_dimensions"), run.inpcrd.get("box_angles"))
            if box:
                box["source"] = (f"restart written by {run.name} (the end of that run)" if own
                                 else f"input coordinates of {run.name}")
                break
        if box:
            break
    if not box:
        box = _box(p.get("box_dimensions"), p.get("box_angles"))
        if box:
            box["source"] = "topology (as built by tLEaP, before equilibration)"
    out["box_at_start"] = box
    hrange = p.get("hmr_hydrogen_mass_range")
    if p.get("hmr_active") is not None or hrange:
        out["hydrogen_masses"] = OrderedDict([
            ("repartitioned", p.get("hmr_active")),
            ("range_amu", [round(x, 4) for x in hrange] if isinstance(hrange, list) else None),
            ("summary", p.get("hmr_hydrogen_mass_summary")),
            ("basis", "topology masses"),
        ])
    hints: Dict[str, Any] = OrderedDict()
    if p.get("force_field_type"):
        hints["FORCE_FIELD_TYPE"] = p["force_field_type"]
    features = [f for f in p.get("force_field_features") or []
                if isinstance(f, str) and not f.startswith(("Orthorhombic", "Truncated",
                                                            "Box/density", "Contains Ions"))]
    if features:
        hints["features"] = features
    title = p.get("title")
    if isinstance(title, str) and title.strip() and title.strip() != "default_name":
        hints["title"] = title.strip()
    out["force_field_hints"] = hints
    out["solvent"] = p.get("solvent_type")
    return out


def _lineages(runs: List["_Run"], summary: Dict[str, Any]) -> str:
    """Tag runs with their replica. Returns how the tags were obtained."""
    if any(r.lineage for r in runs):
        return "declared per run in summary.json"
    totals = _dict(summary.get("totals"))
    declared = _dict(summary.get("lineages"))
    if not declared and not _num(totals.get("lineage_count")):
        return "none"
    # An older summary.json names the replicas in its totals but not on each run. The
    # directory layout is the rule `discover` used to tag them; apply it to the run files.
    from ambermeta.lineages import infer_lineages_from_layout
    paths = {r.index: r.file_path() for r in runs}
    present = [p for p in paths.values() if p]
    if not present:
        return "count only (summary.json has no per-run replica tags)"
    root = os.path.commonpath([p.rsplit("/", 1)[0] if "/" in p else "" for p in present]
                              ) if len(present) > 1 else ""
    root = root.replace("\\", "/")
    names: Dict[int, str] = {}
    for idx, p in paths.items():
        if not p:
            continue
        rel = p[len(root):].lstrip("/") if root and p.startswith(root) else p
        names[idx] = os.path.splitext(rel)[0]
    try:
        tags = infer_lineages_from_layout(sorted(set(names.values())))
    except Exception:  # noqa: BLE001 - a fallback must never cost the whole digest
        tags = {}
    if not tags:
        return "count only (summary.json has no per-run replica tags)"
    for r in runs:
        r.lineage = tags.get(names.get(r.index, ""))
    return ("inferred from the directory layout (this summary.json predates per-run "
            "replica tags)")


def _replicas(runs: List["_Run"], summary: Dict[str, Any], basis: str) -> Dict[str, Any]:
    members = sorted({r.lineage for r in runs if r.lineage}, key=_natural)
    totals = _dict(summary.get("totals"))
    out: Dict[str, Any] = OrderedDict()
    count = len(members) or int(totals.get("lineage_count") or 0)
    out["count"] = count or 1
    if count <= 1:
        out["note"] = "one chain of runs; no replicas declared"
        return out
    out["basis"] = basis
    if members:
        out["names"] = members[:MAX_REPLICA_NAMES] + (
            [f"... {len(members) - MAX_REPLICA_NAMES} more"]
            if len(members) > MAX_REPLICA_NAMES else [])
    shared = [r for r in runs if not r.lineage]
    if shared and members:
        phases = OrderedDict()
        for r in shared:
            phases[r.group] = None
        out["shared_runs"] = OrderedDict([("runs", len(shared)),
                                          ("phases", list(phases))])
    if members:
        by_name = {r.name: r for r in runs}
        stems = {}
        for r in runs:
            restrt = _basename(_dict(_dict(r.stage.get("files")).get("mdout")).get("filename"))
            stems[os.path.splitext(_basename(r.name) or "")[0]] = r
            if restrt:
                stems.setdefault(os.path.splitext(restrt)[0], r)
        heads: "OrderedDict[str, _Run]" = OrderedDict()
        for r in runs:
            if r.lineage and r.lineage not in heads:
                heads[r.lineage] = r
        branch: Counter = Counter()
        unknown = 0
        for member, head in heads.items():
            parent = head.stage.get("continues_from")
            if not parent:
                stem = os.path.splitext(_basename(head.inpcrd.get("filename")) or "")[0]
                candidate = stems.get(stem)
                parent = candidate.name if candidate is not None and candidate is not head else None
            parent_run = by_name.get(parent) if parent else None
            if parent_run is not None and parent_run.lineage != member:
                label = (f"{parent} (shared run)" if not parent_run.lineage
                         else f"{parent} (replica {parent_run.lineage})")
                branch[label] += 1
            else:
                unknown += 1
        if branch:
            out["branch_from"] = [OrderedDict([("run", k), ("replicas", n)])
                                  for k, n in branch.most_common(MAX_NAMES)]
        if unknown:
            out["replicas_whose_first_run_reads_no_run_of_this_document"] = unknown
        roles_per = Counter()
        for member in members:
            phases = OrderedDict()
            for r in runs:
                if r.lineage == member:
                    phases[r.group] = None
            roles_per[" -> ".join(phases)] += 1
        out["phases_per_replica"] = [OrderedDict([("phases", k), ("replicas", n)])
                                     for k, n in roles_per.most_common(MAX_NAMES)]
    seeds = [(r, r.echo.get("ig")) for r in runs if isinstance(r.echo.get("ig"), int)]
    if seeds:
        values = [s for _, s in seeds]
        head_seeds = {}
        for r, s in seeds:
            if r.lineage and r.lineage not in head_seeds:
                head_seeds[r.lineage] = s
        out["resolved_seeds"] = OrderedDict([
            ("runs_with_a_seed_in_the_mdout", len(values)),
            ("distinct", len(set(values))),
            ("first_runs_of_replicas_with_distinct_seeds",
             f"{len(set(head_seeds.values()))} of {len(head_seeds)}" if head_seeds else None),
        ])
    return out


def _continuity(runs: List["_Run"]) -> Dict[str, Any]:
    gaps = [(r, _num(r.stage.get("observed_gap_ps"))) for r in runs]
    gaps = [(r, g) for r, g in gaps if g is not None]
    out: Dict[str, Any] = OrderedDict()
    out["links_measured"] = len(gaps)
    if not gaps:
        return out
    tol = 1e-3
    out["contiguous"] = sum(1 for _, g in gaps if abs(g) <= tol)
    positive = [g for _, g in gaps if g > tol]
    negative = [g for _, g in gaps if g < -tol]
    if positive:
        out["with_gap"] = OrderedDict([("links", len(positive)),
                                       ("largest_ps", _round(max(positive), 6))])
    if negative:
        out["with_overlap"] = OrderedDict([("links", len(negative)),
                                           ("largest_ps", _round(-min(negative), 6))])
    notes = sum(1 for r in runs for n in r.stage.get("continuity") or []
                if isinstance(n, str) and not n.startswith("INFO"))
    if notes:
        out["continuity_findings"] = notes
    out["basis"] = ("the clock of each run's input coordinates against the end of the run "
                    "before it")
    return out


_PATHISH = re.compile(r"[^\s'\"(),;]*[/\\][^\s'\"(),;]*")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _shorten(message: str) -> str:
    text = _PATHISH.sub(lambda m: _basename(m.group(0)) or m.group(0), message)
    return text if len(text) <= 300 else text[:297] + "..."


def _pattern(kind: str, message: str, name: str) -> str:
    text = message
    if name and text.startswith(name):
        text = text[len(name):]
    text = _PATHISH.sub("<path>", text)
    text = re.sub(r"'[^']*'", "'<name>'", text)
    text = _NUMBER.sub("#", text)
    return f"{kind}|{text}"


def _findings(runs: List["_Run"], summary: Dict[str, Any]) -> Dict[str, Any]:
    items: List[Tuple[str, str, Optional[str], Optional[str]]] = []  # kind, msg, run, member
    for r in runs:
        typed = {}
        for f in r.stage.get("findings") or []:
            if isinstance(f, dict) and isinstance(f.get("message"), str):
                typed[f["message"]] = str(f.get("kind") or "run_check")
        continuity = set(n for n in r.stage.get("continuity") or [] if isinstance(n, str))
        seen = set()
        for msg in r.stage.get("validation") or []:
            if not isinstance(msg, str) or msg.startswith("INFO") or msg in seen:
                continue
            seen.add(msg)
            kind = typed.get(msg) or ("continuity" if msg in continuity else "run_note")
            items.append((kind, msg, r.name, r.lineage))
        for msg, kind in typed.items():
            if msg not in seen:
                items.append((kind, msg, r.name, r.lineage))
        for err in r.stage.get("load_errors") or []:
            if isinstance(err, dict):
                msg = (f"{err.get('kind', 'file')} could not be read "
                       f"({err.get('error_type', 'error')}): {_basename(err.get('path')) or ''}")
                items.append(("unreadable_file", msg, r.name, r.lineage))
    for card in summary.get("findings") or []:
        if isinstance(card, dict):
            msg = str(card.get("title") or card.get("evidence") or "")
            items.append((str(card.get("kind") or "document"), msg, None, card.get("lineage")))
    for f in summary.get("lineage_findings") or []:
        if isinstance(f, dict):
            items.append((f"replicas_{f.get('kind', 'finding')}",
                          f"{f.get('severity', '')}: {f.get('message', '')}".strip(": "),
                          None, None))

    groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for kind, msg, run, member in items:
        key = _pattern(kind, msg, run or "")
        g = groups.setdefault(key, {"kind": kind, "example": _shorten(msg), "count": 0,
                                    "example_run": run, "replicas": set()})
        g["count"] += 1
        if member:
            g["replicas"].add(member)
    ranked = sorted(groups.values(), key=lambda g: -g["count"])
    listed = []
    for g in ranked[:MAX_FINDINGS]:
        entry = OrderedDict([("kind", g["kind"]), ("occurrences", g["count"]),
                             ("example", g["example"])])
        if g["example_run"]:
            entry["example_run"] = g["example_run"]
        if len(g["replicas"]) > 1:
            entry["replicas"] = len(g["replicas"])
        listed.append(entry)
    out: Dict[str, Any] = OrderedDict([("total", len(items)), ("patterns", len(groups)),
                                       ("grouped", listed)])
    if len(groups) > MAX_FINDINGS:
        out["more_patterns"] = len(groups) - MAX_FINDINGS
    out["note"] = ("findings are what AmberMeta found to check in the run files; "
                   "INFO remarks are left out")
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_methods_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """The methods summary of a `summary.json` dict (``SimulationProtocol.to_dict()``).

    Returns a JSON-ready dict: provenance, software, system, replicas, the protocol as
    phases in execution order with each setting stated once, observed statistics,
    continuity, grouped findings, and what the run files cannot say. Works on summaries
    written by older AmberMeta versions, with less detail.
    """
    from ambermeta import __version__

    if not isinstance(summary, dict):
        raise TypeError("build_methods_summary expects the summary.json object (a dict)")
    stages = [s for s in summary.get("stages") or [] if isinstance(s, dict)]
    runs = [_Run(i, s) for i, s in enumerate(stages)]
    lineage_basis = _lineages(runs, summary)
    multi = len({r.lineage for r in runs if r.lineage}) >= 1 and lineage_basis != "none"

    _assign_groups(runs)
    groups: "OrderedDict[str, List[_Run]]" = OrderedDict()
    for r in runs:
        groups.setdefault(r.group, []).append(r)

    totals = _dict(summary.get("totals"))
    project: Dict[str, Any] = OrderedDict()
    project["runs"] = len(runs)
    project["runs_with_output"] = sum(1 for r in runs if r.has_output)
    project["finished_runs"] = sum(1 for r in runs if r.finished)
    queued = sum(1 for r in runs if r.queued)
    if queued:
        project["queued_runs"] = queued
    if _num(totals.get("time_ps")) is not None:
        project["simulated_time_ns"] = _round(totals["time_ps"] / 1000.0, 6)
        project["simulated_time_basis"] = ("measured from the mdout files: what the runs "
                                           "ran, not what the mdins asked for")
    project["phases"] = len(groups)

    out: Dict[str, Any] = OrderedDict()
    out["schema_version"] = SCHEMA_VERSION
    out["generator"] = OrderedDict([("name", "AmberMeta"), ("version", __version__)])
    out["about"] = (
        "Methods summary of an AMBER simulation project, written by AmberMeta from its "
        "summary.json, which AmberMeta reads from the run files (topology, mdin, mdout, "
        "coordinates). The protocol is given per phase, in execution order; each setting "
        "is stated once with the number of runs that share it when not all do, and the "
        "runs that differ are listed as other values. 'source' says where a value comes "
        "from (see 'sources'). Nothing here names a force field, a water model or a "
        "preparation step unless a run file states it; see 'not_in_run_files'.")
    out["sources"] = _SOURCES
    out["project"] = project
    out["software"] = _software(runs)
    out["system"] = _system(runs)
    out["replicas"] = _replicas(runs, summary, lineage_basis)
    out["protocol"] = [_phase(name, members, multi) for name, members in groups.items()]
    out["continuity"] = _continuity(runs)
    out["findings"] = _findings(runs, summary)
    out["not_in_run_files"] = NOT_IN_RUN_FILES
    return _prune(out)


_INLINE_WIDTH = 100


def dumps_methods_summary(digest: Any) -> str:
    """The digest as JSON text: indented, with every object or list that fits in
    100 characters kept on one line. A setting then reads as one line
    (`"cut": {"value": 9.0, "source": "mdin"}`), and the file stays about half the size
    of the same document indented throughout."""
    def render(value: Any, level: int) -> str:
        flat = json.dumps(value)
        if not isinstance(value, (dict, list)) or not value \
                or len(flat) + level <= _INLINE_WIDTH:
            return flat
        pad = " " * (level + 1)
        if isinstance(value, dict):
            items = [f"{pad}{json.dumps(str(k))}: {render(v, level + 1)}"
                     for k, v in value.items()]
            return "{\n" + ",\n".join(items) + "\n" + " " * level + "}"
        items = [f"{pad}{render(v, level + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + " " * level + "]"
    return render(digest, 0) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m ambermeta.methods_summary summary.json [-o methods_summary.json]`."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m ambermeta.methods_summary",
        description="Rebuild the methods summary from an existing summary.json "
                    "(or summary.yaml).")
    parser.add_argument("summary", help="summary.json written by `ambermeta plan`")
    parser.add_argument("-o", "--output", help="where to write the methods summary "
                                               "(default: standard output)")
    args = parser.parse_args(argv)
    with open(args.summary, "r", encoding="utf-8") as fh:
        if args.summary.lower().endswith((".yaml", ".yml")):
            import yaml
            data = yaml.safe_load(fh)
        else:
            data = json.load(fh)
    text = dumps_methods_summary(build_methods_summary(data))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
