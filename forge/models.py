"""Data models for the FORGE system."""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class Status(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    BLACK = "BLACK"


class Classification(str, Enum):
    ACTIVE = "ACTIVE"
    LEGACY = "LEGACY"
    BACKUP = "BACKUP"
    TEMPLATE = "TEMPLATE"
    EXPERIMENT = "EXPERIMENT"
    DUPLICATE = "DUPLICATE"
    ARCHIVED = "ARCHIVED"
    CANDIDATE_FOR_MERGE = "CANDIDATE_FOR_MERGE"
    UNKNOWN = "UNKNOWN"


class Priority(str, Enum):
    P0 = "P0_SECURITY"
    P1 = "P1_NOT_EXECUTABLE"
    P2 = "P2_BACKEND_BROKEN"
    P3 = "P3_TOOLING_BROKEN"
    P4 = "P4_TESTS_DOCS"
    P5 = "P5_ORGANIZATION"
    P6 = "P6_OPTIMIZATION"


class Category(str, Enum):
    CORE = "CORE"
    FULLSTACK = "FULLSTACK"
    PRODUCTS = "PRODUCTS"
    AION_AGENTS = "AION_AGENTS"
    DUCK = "DUCK"
    SKILLS = "SKILLS"
    AI_COMPUTE = "AI_COMPUTE"
    VOICE = "VOICE"
    DOCS_BOOKS = "DOCS_BOOKS"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    UNKNOWN = "UNKNOWN"


@dataclass
class GitState:
    repo: bool = False
    branch: str = ""
    dirty: int = 0
    remote: str = "none"
    last_commit: str = ""
    unpushed: int = 0


@dataclass
class Project:
    name: str
    path: str = ""
    repository: str = ""
    visibility: str = ""
    archived: bool = False
    languages: list = field(default_factory=list)
    framework: list = field(default_factory=list)
    stack: str = ""
    status: str = Status.BLACK.value
    classification: str = Classification.UNKNOWN.value
    category: str = Category.UNKNOWN.value
    priority: str = ""
    frontend: str = ""
    backend: str = ""
    database: str = ""
    deployment: str = ""
    has_tests: bool = False
    has_readme: bool = False
    has_ci: bool = False
    has_docker: bool = False
    has_env_example: bool = False
    has_license: bool = False
    has_gitignore: bool = False
    file_count: int = 0
    git: GitState = field(default_factory=GitState)
    issues: list = field(default_factory=list)
    recommended_action: str = ""
    frozen: bool = False

    def to_dict(self):
        return asdict(self)

    def score(self) -> int:
        s = 0
        if self.has_readme: s += 10
        if self.has_license: s += 5
        if self.has_gitignore: s += 5
        if self.has_ci: s += 10
        if self.has_tests: s += 15
        if self.has_env_example: s += 5
        if self.has_docker: s += 5
        if self.git.repo: s += 5
        if self.git.remote and self.git.remote != "none": s += 10
        if self.git.dirty == 0: s += 10
        if self.file_count > 0: s += 5
        if self.stack: s += 5
        if self.status == Status.GREEN.value: s += 10
        return min(s, 100)


@dataclass
class Issue:
    project: str
    priority: str
    description: str
    fix: str = ""
    resolved: bool = False


@dataclass
class ForgeReport:
    timestamp: str = ""
    repos_scanned_local: int = 0
    repos_scanned_github: int = 0
    projects_green: int = 0
    projects_yellow: int = 0
    projects_red: int = 0
    projects_black: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    issues_pending: int = 0
    files_created: list = field(default_factory=list)
    files_modified: list = field(default_factory=list)
    frontend_modified: int = 0
    tests_run: int = 0
    tests_pass: int = 0
    tests_fail: int = 0

    def to_dict(self):
        return asdict(self)
