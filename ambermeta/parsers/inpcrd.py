from __future__ import annotations

from dataclasses import dataclass

from ambermeta.parse_cache import cached_parse
from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import inpcrd as legacy


@dataclass
class InpcrdData(MetadataBase):
    details: legacy.InpcrdMetadata | None = None


class InpcrdParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> InpcrdData:
        # Memoised on the file's identity+mtime+size; see ambermeta/parse_cache.py. The
        # whole inpcrd is re-read only when it has actually changed, which is what makes a
        # second Validate over an unchanged tree cheap instead of another full pass.
        return cached_parse("inpcrd", self.filename, self._parse)

    def _parse(self) -> InpcrdData:
        details = legacy.parse_inpcrd(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return InpcrdData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["InpcrdParser", "InpcrdData"]
