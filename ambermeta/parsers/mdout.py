from __future__ import annotations

from dataclasses import dataclass

from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdout as legacy


@dataclass
class MdoutData(MetadataBase):
    details: legacy.MdoutMetadata | None = None


class MdoutParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdoutData:
        details = legacy.parse_mdout(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdoutData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdoutParser", "MdoutData"]
