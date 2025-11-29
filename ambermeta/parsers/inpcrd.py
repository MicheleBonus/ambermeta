from __future__ import annotations

from dataclasses import dataclass

from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import inpcrd as legacy


@dataclass
class InpcrdData(MetadataBase):
    details: legacy.InpcrdMetadata | None = None


class InpcrdParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> InpcrdData:
        details = legacy.parse_inpcrd(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return InpcrdData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["InpcrdParser", "InpcrdData"]
