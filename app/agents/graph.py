"""
LangGraph Multi-Agent 리뷰 워크플로우.

┌─────────────────────────────────────────────────────────────┐
│ 워크플로우 구조                                              │
│                                                              │
│   merge_diff (LLM 0회)                                       │
│       │                                                      │
│       ├─→ review_bugs          (LLM 1회)                     │
│       ├─→ review_suggestions   (LLM 1회)                     │
│       └─→ summarize_changes    (LLM 1회)                     │
│               │                                              │
│           summarize_review     (LLM 1회)                     │
│               │                                              │
│           generate_report      (LLM 0회)                     │
│               │                                              │
│              END                                             │
│                                                              │
│   총 LLM 호출: 4회 (파일 수 무관)                             │
└─────────────────────────────────────────────────────────────┘

LLM 호출 최소화 전략
━━━━━━━━━━━━━━━━━━
파일별/diff별로 LLM을 호출하지 않는다.
merge_diff 노드에서 전체 파일의 diff를 하나의 텍스트로 병합한 뒤,
에이전트당 1회씩만 LLM을 호출한다.

예: 파일 10개 PR
  - 파일별 호출 방식: 10 × 3 에이전트 = 30회 (비용 ×)
  - 병합 호출 방식:   1 × 3 에이전트 + 1 종합 = 4회 (비용 ○)
"""

import logging
from datetime import datetime
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, StateGraph

from app.agents.prompts import (
    BUG_REVIEWER_PROMPT,
    CHANGE_SUMMARY_PROMPT,
    REPORT_TEMPLATE,
    SUGGESTION_REVIEWER_PROMPT,
    SUMMARIZER_PROMPT,
)
from app.agents.state import ReviewState
from app.config import settings

logger = logging.getLogger(__name__)

# ── LLM 인스턴스 ───────────────────────────────────────
# LangChain의 ChatAnthropic 래퍼를 사용하여 Claude API를 호출한다.
# max_tokens=2048: 리뷰 결과가 잘리지 않도록 충분히 설정
llm = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    api_key=settings.anthropic_api_key,
    max_tokens=2048,
)


# ── 노드 1: diff 병합 (LLM 호출 없음) ──────────────────


def merge_diff(state: ReviewState) -> dict:
    """전체 파일의 diff를 하나의 텍스트로 병합한다.

    이 노드의 핵심 목적:
    - 이후 모든 에이전트가 동일한 merged_diff를 공유
    - 파일 수와 무관하게 에이전트당 LLM 1회 호출로 충분하게 만듦

    입력: state["files"] — [{filename, status, additions, deletions, patch}]
    출력: {"merged_diff": "### file1.py (modified) ...\n### file2.py ..."}
    """
    parts = []
    for f in state["files"]:
        # 파일 헤더: 파일명, 변경 유형, 라인 증감
        header = (
            f"### {f['filename']} ({f['status']}) "
            f"[+{f.get('additions', 0)} / -{f.get('deletions', 0)}]"
        )
        parts.append(f"{header}\n```diff\n{f['patch']}\n```")

    merged = "\n\n".join(parts)
    logger.info(
        "merge_diff: %d개 파일 → %d자 텍스트로 병합",
        len(state["files"]),
        len(merged),
    )
    return {"merged_diff": merged}


# ── 노드 2: 버그 탐지 에이전트 (LLM 1회) ──────────────


def review_bugs(state: ReviewState) -> dict:
    """전체 diff에서 잠재적 버그를 탐지한다.

    프롬프트에 전체 merged_diff를 한 번에 전달하여
    파일 수와 관계없이 LLM 1회 호출로 처리.
    """
    prompt = BUG_REVIEWER_PROMPT.format(diff=state["merged_diff"])
    result = llm.invoke(prompt)
    logger.info("review_bugs 완료 (%d자)", len(result.content))
    return {"bug_review": result.content}


# ── 노드 3: 개선 제안 에이전트 (LLM 1회) ──────────────


def review_suggestions(state: ReviewState) -> dict:
    """전체 diff에서 개선 가능한 부분을 제안한다.

    파일당 최대 3개 제안, 영향도 순 정렬을 프롬프트에서 지시.
    """
    prompt = SUGGESTION_REVIEWER_PROMPT.format(diff=state["merged_diff"])
    result = llm.invoke(prompt)
    logger.info("review_suggestions 완료 (%d자)", len(result.content))
    return {"suggestion_review": result.content}


# ── 노드 4: 변경점 정리 에이전트 (LLM 1회) ────────────


def summarize_changes(state: ReviewState) -> dict:
    """변경사항을 한국어로 정리 요약한다.

    리뷰(critique)가 아닌 문서화(description) 목적.
    변경 개요, 파일별 변경사항, 영향 범위를 구조화하여 작성.
    """
    meta = state["pr_meta"]
    prompt = CHANGE_SUMMARY_PROMPT.format(
        diff=state["merged_diff"],
        title=meta.get("title", ""),
        head_branch=meta.get("head_branch", ""),
        base_branch=meta.get("base_branch", ""),
    )
    result = llm.invoke(prompt)
    logger.info("summarize_changes 완료 (%d자)", len(result.content))
    return {"change_summary": result.content}


# ── 노드 5: 리뷰 종합 (LLM 1회) ──────────────────────


def summarize_review(state: ReviewState) -> dict:
    """버그 리뷰 + 개선 제안을 종합하여 게시용 코멘트를 생성한다.

    한국어 마크다운으로 출력하며, 앞에 🤖 헤더를 붙여
    자동 생성 코멘트임을 명시한다.
    """
    prompt = SUMMARIZER_PROMPT.format(
        bug_review=state["bug_review"],
        suggestion_review=state["suggestion_review"],
    )
    result = llm.invoke(prompt)
    header = "🤖 **AI Code Review**\n\n"
    return {"final_comment": header + result.content}


# ── 노드 6: 리포트 생성 (LLM 호출 없음) ──────────────


def generate_report(state: ReviewState) -> dict:
    """마크다운 리포트를 생성하고 파일로 저장한다.

    LLM을 사용하지 않고 REPORT_TEMPLATE에 값을 채워넣는 방식.
    리포트에는 변경점 요약 + 리뷰 결과가 모두 포함된다.

    파일명 형식: review_{제목}_{타임스탬프}.md
    """
    meta = state["pr_meta"]
    total_add = sum(f.get("additions", 0) for f in state["files"])
    total_del = sum(f.get("deletions", 0) for f in state["files"])

    report = REPORT_TEMPLATE.format(
        title=meta.get("title", "Untitled"),
        html_url=meta.get("html_url", ""),
        author=meta.get("author", "unknown"),
        head_branch=meta.get("head_branch", ""),
        base_branch=meta.get("base_branch", ""),
        changed_files=len(state["files"]),
        additions=total_add,
        deletions=total_del,
        change_summary=state["change_summary"],
        bug_review=state["bug_review"],
        suggestion_review=state["suggestion_review"],
    )

    # 파일 저장
    output_dir = Path(settings.report_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 파일명에 사용 불가한 문자 제거
    safe_title = meta.get("title", "pr").replace(" ", "_")[:30]
    safe_title = "".join(c for c in safe_title if c.isalnum() or c in "_-")
    filename = f"review_{safe_title}_{timestamp}.md"
    filepath = output_dir / filename
    filepath.write_text(report, encoding="utf-8")

    logger.info("리포트 저장: %s", filepath)
    return {"report_md": report, "report_path": str(filepath)}


# ── 그래프 빌드 ─────────────────────────────────────────


def build_review_graph() -> StateGraph:
    """Multi-Agent 리뷰 그래프를 컴파일하여 반환한다.

    LangGraph의 StateGraph를 사용하여 노드 간 의존관계를 정의.
    현재는 순차 실행 (안정성 우선).
    향후 LangGraph의 Send API로 병렬화 가능 (review_bugs, review_suggestions,
    summarize_changes를 동시에 실행하면 약 3배 빨라짐).
    """
    graph = StateGraph(ReviewState)

    # 노드 등록
    graph.add_node("merge_diff", merge_diff)
    graph.add_node("review_bugs", review_bugs)
    graph.add_node("review_suggestions", review_suggestions)
    graph.add_node("summarize_changes", summarize_changes)
    graph.add_node("summarize_review", summarize_review)
    graph.add_node("generate_report", generate_report)

    # 엣지 정의 (순차 실행)
    graph.set_entry_point("merge_diff")
    graph.add_edge("merge_diff", "review_bugs")
    graph.add_edge("review_bugs", "review_suggestions")
    graph.add_edge("review_suggestions", "summarize_changes")
    graph.add_edge("summarize_changes", "summarize_review")
    graph.add_edge("summarize_review", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()
