"""
LangGraph 워크플로우 공유 상태 정의.

TypedDict를 사용하여 노드 간 전달되는 데이터 구조를 정의한다.
각 노드는 상태의 일부를 읽고, 업데이트할 필드만 반환한다.
"""

from typing import TypedDict


class ReviewState(TypedDict):
    """Multi-Agent 리뷰 워크플로우에서 노드 간 공유되는 상태.

    흐름:
    1. files, pr_meta         ← 외부에서 초기값 주입
    2. merged_diff            ← merge_diff 노드가 생성
    3. bug_review, suggestion_review, change_summary
                              ← 각 에이전트 노드가 생성
    4. final_comment          ← summarize_review 노드가 생성
    5. report_md, report_path ← generate_report 노드가 생성
    """

    # ── 입력 (외부 주입) ────────────────────────────────
    files: list[dict]       # [{filename, status, additions, deletions, patch}]
    pr_meta: dict           # {title, author, head_branch, base_branch, html_url, ...}

    # ── 중간 처리 ──────────────────────────────────────
    # 전체 파일의 diff를 하나로 합친 텍스트
    # → 에이전트당 LLM 1회 호출로 충분하게 만듦 (비용 최소화)
    merged_diff: str

    # ── 에이전트 산출물 ────────────────────────────────
    bug_review: str         # 버그 탐지 리뷰 결과
    suggestion_review: str  # 개선 제안 리뷰 결과
    change_summary: str     # 변경점 정리 요약 (문서화용, 리뷰와 별개)

    # ── 최종 출력 ──────────────────────────────────────
    final_comment: str      # PR/커밋에 게시할 코멘트
    report_md: str          # 마크다운 리포트 전문
    report_path: str        # 저장된 리포트 파일 경로
