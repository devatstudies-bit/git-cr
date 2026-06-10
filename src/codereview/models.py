from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class StagedFile:
    path: Path
    content: str
    diff: str
    language: str


@dataclass
class Issue:
    file: Path
    line: int
    severity: Severity
    message: str
    rule: str = ""
    suggestion: str = ""  # populated lazily when user requests preview


@dataclass
class FixResult:
    issue: Issue
    applied: bool
    files_changed: list[Path] = field(default_factory=list)
    error: str = ""
