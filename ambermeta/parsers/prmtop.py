from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ambermeta.parse_cache import cached_parse
from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import prmtop as legacy


@dataclass
class PrmtopData(MetadataBase):
    details: legacy.PrmtopMetadata | None = None


class PrmtopParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> PrmtopData:
        # Memoised on the file's identity+mtime+size; see ambermeta/parse_cache.py. The
        # whole prmtop is re-read only when it has actually changed, which is what makes a
        # second Validate over an unchanged tree cheap instead of another full pass.
        return cached_parse("prmtop", self.filename, self._parse)

    def _parse(self) -> PrmtopData:
        details = legacy.extract_prmtop_metadata(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return PrmtopData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["PrmtopParser", "PrmtopData"]
