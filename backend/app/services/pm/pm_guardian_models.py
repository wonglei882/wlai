"""PM 一致性守护者 — 数据模型（ConsistencyIssue / ConsistencyCheckResult）

纯数据模型，不依赖 Guardian 实例。
从 pm_consistency_guardian.py 拆分以降低单文件复杂度。
"""


# ============ 一致性警告条目 ============


class ConsistencyIssue:
    def __init__(
        self,
        dimension: str,
        severity: str,
        description: str,
        chapter_number: int | None = None,
        suggestion: str | None = None,
        character: str | None = None,
    ):
        """初始化

        Args:
            self:
            dimension:
            severity:
            description:
            chapter_number:
            suggestion:
            character:

        Returns:
            None
        """
        self.dimension = dimension
        self.severity = severity
        self.description = description
        self.chapter_number = chapter_number
        self.suggestion = suggestion
        self.character = character

    def to_dict(self) -> dict:
        """ToDict

        Args:
            self:

        Returns:
            dict
        """
        return {
            'dimension': self.dimension,
            'severity': self.severity,
            'description': self.description,
            'chapter_number': self.chapter_number,
            'suggestion': self.suggestion,
            'character': self.character,
        }


class ConsistencyCheckResult:
    def __init__(self):
        self.issues: list[ConsistencyIssue] = []
        self.warnings: list[str] = []
        self.passed: bool = True

    def add(self, issue: ConsistencyIssue):
        self.issues.append(issue)
        if issue.severity in ('critical', 'high'):
            self.passed = False

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    def to_dict(self) -> dict:
        """ToDict

        Args:
            self:

        Returns:
            dict
        """
        return {
            'passed': self.passed,
            'total': len(self.issues),
            'critical': sum(1 for i in self.issues if i.severity == 'critical'),
            'high': sum(1 for i in self.issues if i.severity == 'high'),
            'issues': [i.to_dict() for i in self.issues],
            'warnings': self.warnings,
        }

    def to_constraints(self) -> dict:
        """转为 generate-chapter-constraints 格式"""
        return {
            'character_state_warnings': [i.to_dict() for i in self.issues if i.dimension in ('character_state_jump',)],
            'world_drift_warnings': [i.to_dict() for i in self.issues if i.dimension == 'world_drift'],
            'foreshadow_reminders': [i.to_dict() for i in self.issues if i.dimension == 'foreshadow_overdue'],
            'arc_warnings': [i.to_dict() for i in self.issues if i.dimension == 'arc_fracture'],
        }
