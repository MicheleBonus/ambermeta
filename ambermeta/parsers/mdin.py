from __future__ import annotations

from dataclasses import dataclass

from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdin as legacy


@dataclass
class MdinData(MetadataBase):
    details: legacy.MdinMetadata | None = None


class MdinParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdinData:
        details = legacy.parse_mdin_file(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdinData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdinParser", "MdinData"]
