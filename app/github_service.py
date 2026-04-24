"""
GitHub REST API 연동 서비스.

세 가지 주요 기능:
1. PR diff 수집     — /pulls/{number}/files (페이지네이션)
2. Push diff 수집   — /compare/{before}...{after} (커밋 비교)
3. PR 코멘트 게시   — /issues/{number}/comments
4. Commit 코멘트    — /commits/{sha}/comments (push 이벤트용)

참조:
- https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files
- https://docs.github.com/en/rest/commits/commits#compare-two-commits
"""

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# GitHub REST API 파일 목록 최대 per_page 값
PER_PAGE = 100


def _headers() -> dict:
    """GitHub API 인증 및 Accept 헤더를 반환한다."""
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github.v3+json",
    }


def _filter_and_truncate(files_json: list[dict]) -> list[dict]:
    """API 응답에서 대상 확장자만 필터링하고 diff를 max_diff_lines로 자른다.

    Args:
        files_json: GitHub API가 반환한 파일 객체 리스트.
            각 객체는 filename, status, patch, additions, deletions 등을 포함.

    Returns:
        필터링 + 트렁케이트된 파일 정보 리스트.
    """
    target_exts = [e.strip() for e in settings.target_extensions.split(",")]
    result: list[dict] = []

    for f in files_json:
        filename: str = f.get("filename", "")

        # 확장자 필터링
        if not any(filename.endswith(ext) for ext in target_exts):
            continue

        # patch가 없는 경우 (바이너리 파일, renamed-only 등)
        patch = f.get("patch") or ""

        # max_diff_lines 초과 시 잘라냄
        lines = patch.split("\n")
        if len(lines) > settings.max_diff_lines:
            patch = "\n".join(lines[: settings.max_diff_lines])
            patch += f"\n\n... (truncated: {len(lines)} → {settings.max_diff_lines} lines)"

        result.append(
            {
                "filename": filename,
                "status": f.get("status", ""),        # added, modified, removed, renamed
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": patch,
            }
        )

    return result


# ── PR diff 수집 ────────────────────────────────────────


async def fetch_pr_diff(repo_full_name: str, pr_number: int) -> list[dict]:
    """PR의 전체 변경 파일을 페이지네이션으로 수집한다.

    GitHub API: GET /repos/{owner}/{repo}/pulls/{pull_number}/files
    - 한 번에 최대 100개 파일 반환 (per_page=100)
    - 전체 최대 3,000개 파일까지 지원
    - 여러 커밋이 포함된 PR이라도 이 API 한 번으로 모든 파일의 diff를 가져옴

    Args:
        repo_full_name: "owner/repo" 형식. 예: "octocat/Hello-World"
        pr_number: PR 번호. 예: 42

    Returns:
        대상 확장자에 해당하는 파일 정보 리스트.
    """
    all_files: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = (
                f"{GITHUB_API}/repos/{repo_full_name}"
                f"/pulls/{pr_number}/files"
                f"?per_page={PER_PAGE}&page={page}"
            )
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            items = resp.json()

            # 빈 페이지면 종료
            if not items:
                break

            all_files.extend(items)

            # 마지막 페이지 판별: 받은 개수 < per_page이면 더 이상 없음
            if len(items) < PER_PAGE:
                break
            page += 1

    result = _filter_and_truncate(all_files)
    logger.info(
        "PR #%d: fetched %d files total, %d target files (pages: %d)",
        pr_number, len(all_files), len(result), page,
    )
    return result


# ── Push diff 수집 ──────────────────────────────────────


async def fetch_push_diff(
    repo_full_name: str,
    before_sha: str,
    after_sha: str,
) -> list[dict]:
    """두 커밋 간의 diff를 비교하여 변경 파일을 수집한다.

    GitHub API: GET /repos/{owner}/{repo}/compare/{basehead}
    - basehead 형식: "{before}...{after}"
    - push 이벤트에서 before/after SHA를 받아서 사용
    - 응답의 files 배열에 각 파일의 patch(diff)가 포함됨

    주의: before가 "0000000..."이면 새 브랜치 생성이므로
    첫 번째 커밋부터 비교해야 한다. 이 경우 after SHA만 사용.

    Args:
        repo_full_name: "owner/repo" 형식
        before_sha: 푸시 전 HEAD SHA
        after_sha: 푸시 후 HEAD SHA

    Returns:
        대상 확장자에 해당하는 파일 정보 리스트.
    """
    # 새 브랜치 생성 시 before가 null SHA(0000...)이므로 compare 불가
    # 이 경우 after 커밋 단건의 diff를 가져옴
    if before_sha.startswith("0000"):
        url = f"{GITHUB_API}/repos/{repo_full_name}/commits/{after_sha}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
        files_json = data.get("files", [])
    else:
        url = (
            f"{GITHUB_API}/repos/{repo_full_name}"
            f"/compare/{before_sha}...{after_sha}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            data = resp.json()
        files_json = data.get("files", [])

    result = _filter_and_truncate(files_json)
    logger.info(
        "Push %s...%s: fetched %d files total, %d target files",
        before_sha[:7], after_sha[:7], len(files_json), len(result),
    )
    return result


# ── PR 메타데이터 조회 ──────────────────────────────────


async def fetch_pr_metadata(repo_full_name: str, pr_number: int) -> dict:
    """PR 기본 정보를 조회한다.

    GitHub API: GET /repos/{owner}/{repo}/pulls/{pull_number}

    Returns:
        PR 메타 정보 딕셔너리.
    """
    url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        data = resp.json()

    return {
        "title": data.get("title", ""),
        "author": data.get("user", {}).get("login", ""),
        "head_branch": data.get("head", {}).get("ref", ""),
        "base_branch": data.get("base", {}).get("ref", ""),
        "html_url": data.get("html_url", ""),
        "commits": data.get("commits", 0),
        "changed_files": data.get("changed_files", 0),
    }


# ── 코멘트 게시 ────────────────────────────────────────


async def post_pr_comment(repo_full_name: str, pr_number: int, body: str) -> None:
    """PR에 일반 코멘트를 게시한다.

    GitHub API: POST /repos/{owner}/{repo}/issues/{issue_number}/comments
    ※ GitHub에서 PR은 Issue의 일종이므로 issues 엔드포인트를 사용한다.
    """
    url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=_headers(), json={"body": body})
        resp.raise_for_status()
    logger.info("Posted comment on PR #%d", pr_number)


async def post_commit_comment(
    repo_full_name: str,
    commit_sha: str,
    body: str,
) -> None:
    """특정 커밋에 코멘트를 게시한다 (push 이벤트용).

    GitHub API: POST /repos/{owner}/{repo}/commits/{sha}/comments
    """
    url = (
        f"{GITHUB_API}/repos/{repo_full_name}"
        f"/commits/{commit_sha}/comments"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=_headers(), json={"body": body})
        resp.raise_for_status()
    logger.info("Posted comment on commit %s", commit_sha[:7])
