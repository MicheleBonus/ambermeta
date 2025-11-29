from __future__ import annotations

from dataclasses import dataclass

from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdcrd as legacy


@dataclass
class MdcrdData(MetadataBase):
    details: legacy.TrajectoryMetadata | None = None


class MdcrdParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdcrdData:
        details = legacy.parse_mdcrd(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdcrdData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdcrdParser", "MdcrdData"]
