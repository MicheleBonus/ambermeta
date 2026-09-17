from __future__ import annotations

from dataclasses import dataclass

from ambermeta.parse_cache import cached_parse
from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdcrd as legacy


@dataclass
class MdcrdData(MetadataBase):
    details: legacy.TrajectoryMetadata | None = None


class MdcrdParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdcrdData:
        # Memoised on the file's identity+mtime+size; see ambermeta/parse_cache.py. The
        # whole mdcrd is re-read only when it has actually changed, which is what makes a
        # second Validate over an unchanged tree cheap instead of another full pass.
        return cached_parse("mdcrd", self.filename, self._parse)

    def _parse(self) -> MdcrdData:
        details = legacy.parse_mdcrd(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdcrdData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdcrdParser", "MdcrdData"]
