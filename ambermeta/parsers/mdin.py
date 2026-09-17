from __future__ import annotations

from dataclasses import dataclass

from ambermeta.parse_cache import cached_parse
from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdin as legacy


@dataclass
class MdinData(MetadataBase):
    details: legacy.MdinMetadata | None = None


class MdinParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdinData:
        # Memoised on the file's identity+mtime+size; see ambermeta/parse_cache.py. The
        # whole mdin is re-read only when it has actually changed, which is what makes a
        # second Validate over an unchanged tree cheap instead of another full pass.
        return cached_parse("mdin", self.filename, self._parse)

    def _parse(self) -> MdinData:
        details = legacy.parse_mdin_file(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdinData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdinParser", "MdinData"]
