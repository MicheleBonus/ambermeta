from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ambermeta.utils import MetadataBase
import extract_prmtop as legacy


@dataclass
class PrmtopData(MetadataBase):
    details: legacy.PrmtopMetadata | None = None


class PrmtopParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> PrmtopData:
        details = legacy.extract_prmtop_metadata(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return PrmtopData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["PrmtopParser", "PrmtopData"]
