"""Typed errors and the file-load error record used across AmberMeta."""

from dataclasses import dataclass


class AmberMetaError(Exception):
    """Base class for expected AmberMeta failures handled cleanly by the CLI."""


@dataclass
class FileLoadError:
    """A single input file that could not be parsed.

    Distinct from a parser ``warnings`` entry: a warning means "parsed but
    suspicious"; a FileLoadError means "this file could not be parsed at all".
    """

    kind: str          # "prmtop" | "mdin" | "mdout" | "mdcrd" | "inpcrd"
    path: str
    error_type: str    # "missing" | "permission" | "decode" | "malformed"
    message: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "path": self.path,
            "error_type": self.error_type,
            "message": self.message,
        }


def classify_exception(exc: BaseException) -> str:
    """Map an exception raised while opening/parsing a file to an error_type."""
    if isinstance(exc, FileNotFoundError):
        return "missing"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, UnicodeDecodeError):
        return "decode"
    # ValueError, OSError, and anything else parse-related
    return "malformed"
