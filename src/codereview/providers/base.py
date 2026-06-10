from abc import ABC, abstractmethod
from ..models import Issue, FixResult, StagedFile


class AIProvider(ABC):

    @abstractmethod
    def review(self, files: list[StagedFile]) -> list[Issue]:
        """Analyze staged files and return a list of issues."""

    @abstractmethod
    def suggest_fix(self, issue: Issue) -> str:
        """Return a human-readable diff/suggestion string for the issue."""

    @abstractmethod
    def apply_fix(self, issue: Issue, repo_root: str) -> FixResult:
        """Apply the fix for the issue directly to the file on disk."""
