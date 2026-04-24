"""
Webhook 라우터 — GitHub 이벤트 수신, 파싱, 리뷰 오케스트레이션.

지원 이벤트:
1. pull_request (action=opened)   → PR diff 수집 → 리뷰 → PR 코멘트
2. push (target branches)         → compare diff 수집 → 리뷰 → 커밋 코멘트

────────────────────────────────────────────────────────────
GitHub Webhook HTTP 요청 구조 (공식 문서 기반):
────────────────────────────────────────────────────────────

■ 요청 헤더:
  X-GitHub-Event: "pull_request" | "push" | "ping" | ...
  X-GitHub-Delivery: "72d3162e-cc78-11e3-..."   (배달 고유 GUID)
  X-Hub-Signature-256: "sha256=d57c68ca..."     (HMAC-SHA256 서명)
  X-GitHub-Hook-ID: "292430182"                 (웹훅 ID)
  Content-Type: "application/json"
  User-Agent: "GitHub-Hookshot/044aadd"

■ pull_request 이벤트 페이로드 (주요 필드):
  {
    "action": "opened",
    "number": 42,                               ← PR 번호 (최상위)
    "pull_request": {
      "number": 42,
      "title": "...",
      "html_url": "https://github.com/.../pull/42",
      "user": {"login": "octocat"},
      "head": {"ref": "feature-branch", "sha": "..."},
      "base": {"ref": "main", "sha": "..."},
      "commits": 3,
      "additions": 150,
      "deletions": 30,
      "changed_files": 5
    },
    "repository": {
      "id": 1296269,
      "full_name": "octocat/Hello-World"
    },
    "sender": {"login": "octocat"}
  }

■ push 이벤트 페이로드 (주요 필드):
  주의: action 필드가 없다!
  {
    "ref": "refs/heads/main",                   ← 푸시된 브랜치의 전체 ref
    "before": "abc123...",                       ← 푸시 전 HEAD SHA
    "after": "def456...",                        ← 푸시 후 HEAD SHA
    "created": false,
    "deleted": false,
    "commits": [
      {
        "id": "def456...",
        "message": "Fix login bug",
        "author": {"name": "...", "email": "..."},
        "added": ["src/new.py"],
        "modified": ["src/login.py"],
        "removed": []
      }
    ],
    "head_commit": {"id": "def456...", "message": "..."},
    "repository": {
      "id": 1296269,
      "full_name": "octocat/Hello-World"
    },
    "pusher": {"name": "octocat", "email": "..."},
    "sender": {"login": "octocat"}
  }
"""

import hashlib
import hmac
import logging
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request

from app.agents.graph import build_review_graph
from app.config import settings
from app.email_service import send_report_email
from app.github_service import (
    fetch_pr_diff,
    fetch_pr_metadata,
    fetch_push_diff,
    post_commit_comment,
    post_pr_comment,
)
from app.models import PullRequestEvent, PushEvent

logger = logging.getLogger(__name__)
router = APIRouter()

# 그래프를 앱 시작 시 1회만 컴파일 (매 요청마다 재컴파일하지 않음)
review_graph = build_review_graph()


# ── 시그니처 검증 ───────────────────────────────────────


def _verify_signature(payload: bytes, signature: str | None) -> None:
    """GitHub webhook HMAC-SHA256 서명을 검증한다.

    GitHub는 웹훅 전송 시 X-Hub-Signature-256 헤더에
    "sha256={hmac_hex}" 형식의 서명을 포함한다.

    서버 측에서 동일한 secret으로 HMAC를 계산하여 비교한다.
    ※ timing-safe compare를 사용하여 타이밍 공격을 방지.

    secret 미설정 시 검증을 건너뛴다 (개발 환경용).
    """
    if not settings.github_webhook_secret:
        logger.warning("GITHUB_WEBHOOK_SECRET 미설정 — 서명 검증 건너뜀")
        return

    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or invalid signature header")

    expected = hmac.new(
        settings.github_webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(status_code=401, detail="Signature mismatch")


# ── 리뷰 실행 공통 로직 ────────────────────────────────


async def _run_review(
    files: list[dict],
    pr_meta: dict,
) -> dict:
    """Multi-Agent 리뷰 그래프를 실행하고 결과를 반환한다.

    PR 이벤트와 push 이벤트 모두에서 공통으로 사용.

    Args:
        files: 대상 파일 목록 (github_service에서 수집)
        pr_meta: 메타 정보 딕셔너리

    Returns:
        LangGraph 실행 결과 (ReviewState 형태)
    """
    initial_state = {
        "files": files,
        "pr_meta": pr_meta,
        "merged_diff": "",
        "bug_review": "",
        "suggestion_review": "",
        "change_summary": "",
        "final_comment": "",
        "report_md": "",
        "report_path": "",
    }
    result = await review_graph.ainvoke(initial_state)
    return result


# ── 이메일 발송 ─────────────────────────────────────────


async def _send_email(pr_meta: dict, report_path: str) -> None:
    """리뷰 리포트를 이메일로 발송한다."""
    path = Path(report_path) if report_path else None
    title = pr_meta.get("title", "Code Review")
    html_url = pr_meta.get("html_url", "")

    await send_report_email(
        subject=f"[Code Review] {title}",
        body_text=(
            f"코드 리뷰 리포트가 생성되었습니다.\n"
            f"링크: {html_url}\n\n"
            f"첨부된 .md 파일을 확인해주세요."
        ),
        attachment_path=path,
    )


# ── PR 이벤트 처리 ──────────────────────────────────────


async def _handle_pull_request(data: dict) -> dict:
    """pull_request 이벤트를 처리한다.

    흐름:
    1. Pydantic 모델로 페이로드 파싱 + 검증
    2. action == "opened" 인 경우만 처리
    3. GitHub API로 PR diff 수집 (페이지네이션)
    4. Multi-Agent 리뷰 실행
    5. PR 코멘트 게시
    6. 리포트 이메일 발송
    """
    # Pydantic 모델로 안전하게 파싱 (누락 필드는 기본값 사용)
    event = PullRequestEvent.model_validate(data)

    # action 필터: opened만 처리 (synchronize, closed 등은 무시)
    if event.action != "opened":
        logger.info("PR #%d action=%s → 무시", event.number, event.action)
        return {"status": "ignored", "reason": f"action={event.action}"}

    repo = event.repository.full_name
    pr_number = event.number

    # ※ event.number과 event.pull_request.number은 동일한 값
    logger.info(
        "PR #%d opened on %s by %s — '%s'",
        pr_number, repo, event.sender.login,
        event.pull_request.title,
    )

    try:
        # 1) PR 메타데이터 + diff 수집
        pr_meta = await fetch_pr_metadata(repo, pr_number)
        files = await fetch_pr_diff(repo, pr_number)

        if not files:
            logger.info("PR #%d: 대상 파일 없음", pr_number)
            return {"status": "skipped", "reason": "no target files"}

        # 2) Multi-Agent 리뷰 실행 (LLM 4회)
        result = await _run_review(files, pr_meta)

        # 3) PR 코멘트 게시
        await post_pr_comment(repo, pr_number, result["final_comment"])

        # 4) 이메일 발송
        await _send_email(pr_meta, result["report_path"])

        return {"status": "reviewed", "pr": pr_number, "report": result["report_path"]}

    except Exception:
        logger.exception("PR #%d 리뷰 실패", pr_number)
        try:
            await post_pr_comment(
                repo, pr_number,
                "🤖 AI Code Review를 완료하지 못했습니다. 로그를 확인해주세요.",
            )
        except Exception:
            logger.exception("에러 코멘트 게시 실패")
        return {"status": "error"}


# ── Push 이벤트 처리 ────────────────────────────────────


async def _handle_push(data: dict) -> dict:
    """push 이벤트를 처리한다.

    흐름:
    1. Pydantic 모델로 페이로드 파싱
    2. 브랜치 삭제/대상 외 브랜치 필터링
    3. GitHub compare API로 before...after diff 수집
    4. Multi-Agent 리뷰 실행
    5. 마지막 커밋에 코멘트 게시
    6. 리포트 이메일 발송

    push 이벤트의 특이점:
    - action 필드가 없음 (PR과 달리)
    - ref가 "refs/heads/{branch}" 형식
    - before가 "0000..." 이면 새 브랜치 생성
    - deleted=true이면 브랜치 삭제 → diff 없음
    """
    event = PushEvent.model_validate(data)

    # 브랜치 삭제 이벤트는 무시
    if event.deleted:
        logger.info("브랜치 삭제 이벤트 → 무시 (ref=%s)", event.ref)
        return {"status": "ignored", "reason": "branch deleted"}

    # ref에서 브랜치명 추출: "refs/heads/main" → "main"
    branch = event.ref.replace("refs/heads/", "")

    # 대상 브랜치 필터링
    target_branches = [b.strip() for b in settings.target_branches.split(",")]
    if branch not in target_branches:
        logger.info("push to %s → 대상 브랜치 아님 (target: %s)", branch, target_branches)
        return {"status": "ignored", "reason": f"branch '{branch}' not in targets"}

    repo = event.repository.full_name
    commit_count = len(event.commits)
    logger.info(
        "Push to %s/%s by %s — %d commits (%s...%s)",
        repo, branch, event.pusher.name,
        commit_count, event.before[:7], event.after[:7],
    )

    try:
        # 1) compare API로 diff 수집
        files = await fetch_push_diff(repo, event.before, event.after)

        if not files:
            logger.info("Push %s: 대상 파일 없음", event.after[:7])
            return {"status": "skipped", "reason": "no target files"}

        # 2) 메타 정보 구성 (push에는 PR 메타가 없으므로 직접 구성)
        head_commit_msg = ""
        if event.head_commit:
            head_commit_msg = event.head_commit.message.split("\n")[0]  # 첫 줄만

        pr_meta = {
            "title": head_commit_msg or f"Push to {branch}",
            "author": event.pusher.name,
            "head_branch": branch,
            "base_branch": branch,
            "html_url": event.compare,
            "commits": commit_count,
            "changed_files": len(files),
        }

        # 3) Multi-Agent 리뷰 실행 (LLM 4회)
        result = await _run_review(files, pr_meta)

        # 4) 마지막 커밋에 코멘트 게시
        await post_commit_comment(repo, event.after, result["final_comment"])

        # 5) 이메일 발송
        await _send_email(pr_meta, result["report_path"])

        return {
            "status": "reviewed",
            "commit": event.after[:7],
            "report": result["report_path"],
        }

    except Exception:
        logger.exception("Push %s 리뷰 실패", event.after[:7])
        return {"status": "error"}


# ── 메인 엔드포인트 ─────────────────────────────────────


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
):
    """GitHub Webhook 메인 엔드포인트.

    모든 webhook 이벤트가 이 엔드포인트로 들어온다.
    X-GitHub-Event 헤더로 이벤트 유형을 구분하여 적절한 핸들러로 라우팅.

    지원 이벤트:
    - ping          → 웹훅 등록 확인 (GitHub가 자동 전송)
    - pull_request  → PR 리뷰
    - push          → Push 리뷰
    """
    # 1. raw body로 서명 검증 (JSON 파싱 전에 수행해야 함)
    payload = await request.body()
    _verify_signature(payload, x_hub_signature_256)

    logger.info(
        "Webhook 수신: event=%s, delivery=%s",
        x_github_event, x_github_delivery,
    )

    # 2. ping 이벤트 처리 (웹훅 최초 등록 시 GitHub가 전송)
    if x_github_event == "ping":
        logger.info("Ping 이벤트 수신 — 웹훅 연결 확인 완료")
        return {"status": "pong"}

    # 3. 이벤트 유형별 라우팅
    data = await request.json()

    if x_github_event == "pull_request":
        return await _handle_pull_request(data)

    elif x_github_event == "push":
        return await _handle_push(data)

    else:
        # 미지원 이벤트는 무시 (200 반환하여 GitHub 재시도 방지)
        logger.info("미지원 이벤트: %s → 무시", x_github_event)
        return {"status": "ignored", "reason": f"unsupported event: {x_github_event}"}
