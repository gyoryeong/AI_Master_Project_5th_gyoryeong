"""
GitHub Webhook 페이로드 Pydantic 모델.

GitHub 공식 문서 기반으로 작성.
참조: https://docs.github.com/en/webhooks/webhook-events-and-payloads

─────────────────────────────────────────────────────────
■ pull_request 이벤트 (X-GitHub-Event: pull_request)
─────────────────────────────────────────────────────────
GitHub가 PR과 관련된 활동이 발생하면 전송하는 이벤트.
action 필드로 세부 유형을 구분한다.

실제 페이로드 예시 (주요 필드만 발췌):
{
    "action": "opened",              ← "opened" | "synchronize" | "closed" | ...
    "number": 42,                    ← PR 번호 (최상위에도 존재)
    "pull_request": {
        "number": 42,
        "title": "Add dark mode support",
        "html_url": "https://github.com/owner/repo/pull/42",
        "user": {
            "login": "octocat"
        },
        "head": {                    ← PR 소스 브랜치 정보
            "ref": "feature/dark-mode",
            "sha": "abc123..."
        },
        "base": {                    ← PR 타겟(머지 대상) 브랜치 정보
            "ref": "main",
            "sha": "def456..."
        },
        "commits": 3,               ← PR에 포함된 커밋 수
        "additions": 150,
        "deletions": 30,
        "changed_files": 5,
        "merged": false
    },
    "repository": {
        "id": 1296269,
        "full_name": "octocat/Hello-World",
        "html_url": "https://github.com/octocat/Hello-World",
        "owner": { "login": "octocat" }
    },
    "sender": {                      ← 이벤트를 발생시킨 사용자
        "login": "octocat"
    }
}

─────────────────────────────────────────────────────────
■ push 이벤트 (X-GitHub-Event: push)
─────────────────────────────────────────────────────────
브랜치에 커밋이 푸시되면 전송되는 이벤트.
PR 이벤트와 달리 action 필드가 없다.

실제 페이로드 예시 (주요 필드만 발췌):
{
    "ref": "refs/heads/main",        ← 푸시된 브랜치의 전체 ref
    "before": "abc123...",           ← 푸시 전 HEAD 커밋 SHA
    "after": "def456...",            ← 푸시 후 HEAD 커밋 SHA
    "created": false,                ← 새 브랜치 생성 여부
    "deleted": false,                ← 브랜치 삭제 여부
    "forced": false,                 ← force push 여부
    "compare": "https://github.com/owner/repo/compare/abc123...def456",
    "commits": [                     ← 푸시에 포함된 커밋 목록 (최대 20개)
        {
            "id": "def456...",
            "message": "Fix login bug",
            "author": {
                "name": "Ozer",
                "email": "ozer@example.com",
                "username": "ozers"
            },
            "added": ["src/auth.ts"],
            "modified": ["src/login.ts"],
            "removed": []
        }
    ],
    "head_commit": {                 ← 푸시의 마지막(최신) 커밋
        "id": "def456...",
        "message": "Fix login bug",
        "author": { ... }
    },
    "repository": {
        "id": 1296269,
        "full_name": "octocat/Hello-World",
        "owner": { "login": "octocat" }
    },
    "pusher": {                      ← 푸시를 수행한 사용자
        "name": "octocat",
        "email": "octocat@github.com"
    },
    "sender": {
        "login": "octocat"
    }
}

─────────────────────────────────────────────────────────
■ HTTP 요청 헤더 (공통)
─────────────────────────────────────────────────────────
POST /webhook HTTP/1.1
X-GitHub-Event: pull_request          ← 이벤트 유형
X-GitHub-Delivery: 72d3162e-cc78-...  ← 배달 고유 ID (GUID)
X-Hub-Signature-256: sha256=d57c68... ← HMAC-SHA256 서명 (secret 설정 시)
X-GitHub-Hook-ID: 292430182           ← 웹훅 고유 ID
User-Agent: GitHub-Hookshot/044aadd
Content-Type: application/json
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── 공통 하위 모델 ──────────────────────────────────────


class GitHubUser(BaseModel):
    """GitHub 사용자 정보. sender, pusher.name 등에서 사용."""
    login: str = ""


class GitHubOwner(BaseModel):
    """레포지토리 소유자."""
    login: str = ""


class GitHubRepository(BaseModel):
    """repository 객체 — PR/push 이벤트 모두에 포함된다."""
    id: int = 0
    full_name: str = ""                # 예: "octocat/Hello-World"
    html_url: str = ""
    owner: GitHubOwner = Field(default_factory=GitHubOwner)


# ── pull_request 이벤트 모델 ────────────────────────────


class PullRequestRef(BaseModel):
    """PR의 head(소스) 또는 base(타겟) 브랜치 정보."""
    ref: str = ""       # 브랜치명. 예: "feature/dark-mode"
    sha: str = ""       # 해당 브랜치의 최신 커밋 SHA


class PullRequestDetail(BaseModel):
    """pull_request 객체 내부의 PR 상세 정보."""
    number: int = 0
    title: str = ""
    html_url: str = ""
    user: GitHubUser = Field(default_factory=GitHubUser)
    head: PullRequestRef = Field(default_factory=PullRequestRef)
    base: PullRequestRef = Field(default_factory=PullRequestRef)
    commits: int = 0            # PR에 포함된 커밋 수
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    merged: bool = False


class PullRequestEvent(BaseModel):
    """X-GitHub-Event: pull_request 일 때의 전체 페이로드.

    주요 action 값:
    - "opened"      : PR 새로 생성
    - "synchronize" : PR에 새 커밋 추가 (push)
    - "closed"      : PR 닫힘 (merged=true이면 머지)
    - "reopened"    : PR 재오픈
    """
    action: str = ""                    # "opened", "synchronize", "closed", ...
    number: int = 0                     # PR 번호 (최상위)
    pull_request: PullRequestDetail = Field(default_factory=PullRequestDetail)
    repository: GitHubRepository = Field(default_factory=GitHubRepository)
    sender: GitHubUser = Field(default_factory=GitHubUser)


# ── push 이벤트 모델 ───────────────────────────────────


class CommitAuthor(BaseModel):
    """커밋 작성자 정보."""
    name: str = ""
    email: str = ""
    username: str = ""


class PushCommit(BaseModel):
    """push 이벤트에 포함되는 개별 커밋 정보.

    commits 배열에는 최대 20개까지만 포함된다.
    20개 초과 시 GitHub API를 통해 추가 조회 필요.
    """
    id: str = ""                        # 커밋 SHA
    message: str = ""
    author: CommitAuthor = Field(default_factory=CommitAuthor)
    added: list[str] = Field(default_factory=list)      # 추가된 파일 경로
    modified: list[str] = Field(default_factory=list)    # 수정된 파일 경로
    removed: list[str] = Field(default_factory=list)     # 삭제된 파일 경로


class Pusher(BaseModel):
    """push를 수행한 사용자 (sender와 다를 수 있음)."""
    name: str = ""
    email: str = ""


class PushEvent(BaseModel):
    """X-GitHub-Event: push 일 때의 전체 페이로드.

    주의: push 이벤트에는 action 필드가 없다.
    브랜치 삭제 시 deleted=true, after="0000000..." 이 된다.
    """
    ref: str = ""                       # 예: "refs/heads/main"
    before: str = ""                    # 푸시 전 HEAD SHA
    after: str = ""                     # 푸시 후 HEAD SHA
    created: bool = False               # 새 브랜치 생성 여부
    deleted: bool = False               # 브랜치 삭제 여부
    forced: bool = False                # force push 여부
    compare: str = ""                   # 비교 URL
    commits: list[PushCommit] = Field(default_factory=list)
    head_commit: PushCommit | None = None   # 푸시의 마지막 커밋
    repository: GitHubRepository = Field(default_factory=GitHubRepository)
    pusher: Pusher = Field(default_factory=Pusher)
    sender: GitHubUser = Field(default_factory=GitHubUser)
