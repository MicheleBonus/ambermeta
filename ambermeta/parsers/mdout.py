from __future__ import annotations

from dataclasses import dataclass

from ambermeta.parse_cache import cached_parse
from ambermeta.utils import MetadataBase
from ambermeta.legacy_extractors import mdout as legacy


@dataclass
class MdoutData(MetadataBase):
    details: legacy.MdoutMetadata | None = None


class MdoutParser:
    def __init__(self, filename: str):
        self.filename = filename

    def parse(self) -> MdoutData:
        # Memoised on the file's identity+mtime+size; see ambermeta/parse_cache.py. The
        # whole mdout is re-read only when it has actually changed, which is what makes a
        # second Validate over an unchanged tree cheap instead of another full pass.
        return cached_parse("mdout", self.filename, self._parse)

    def _parse(self) -> MdoutData:
        details = legacy.parse_mdout(self.filename)
        warnings = getattr(details, "warnings", []) or []
        return MdoutData(filename=self.filename, warnings=list(warnings), details=details)


__all__ = ["MdoutParser", "MdoutData"]
