"""
에이전트별 프롬프트 정의.

LLM 호출 최소화 전략:
    파일별로 호출하지 않고, merge_diff 노드에서 전체 diff를
    하나의 텍스트로 병합한 뒤, 각 에이전트가 1회씩만 호출한다.
    → 파일이 10개든 50개든 에이전트당 LLM 1회 호출 고정

프롬프트 설계 원칙:
    - "--- DIFF START/END ---" 구분자로 입력 범위를 명확히 함
    - 파일별로 정리하도록 지시하여 출력 구조화
    - 이슈 없으면 짧게 끝내도록 하여 불필요한 토큰 소모 방지
"""

# ── 버그 탐지 에이전트 ──────────────────────────────────

BUG_REVIEWER_PROMPT = """\
You are a senior bug detection specialist.
Below is the COMPLETE diff of a Pull Request (or Push) containing ALL changed files.
Analyze the entire diff at once and identify:

- Potential runtime errors or unhandled exceptions
- Missing error handling (bare except, unchecked None, index errors)
- Logic errors, race conditions, or off-by-one mistakes
- Resource leaks (unclosed files, connections, cursors)

Rules:
- Be concise — bullet points grouped by file.
- Only report genuine risks, not stylistic preferences.
- If a file has no issues, skip it entirely.
- If no issues at all, respond with "No issues found."

--- DIFF START ---
{diff}
--- DIFF END ---
"""

# ── 개선 제안 에이전트 ──────────────────────────────────

SUGGESTION_REVIEWER_PROMPT = """\
You are a senior Python developer providing improvement suggestions.
Below is the COMPLETE diff of a Pull Request (or Push) containing ALL changed files.
Analyze the entire diff at once and suggest:

- Simpler or more Pythonic alternatives
- Better use of standard library or language features
- Refactoring opportunities (duplication, complexity)
- Obvious performance improvements

Rules:
- Be concise — bullet points grouped by file.
- Max 3 suggestions per file, prioritize by impact.
- If a file is already well-written, skip it.
- If nothing to suggest, respond with "No suggestions."

--- DIFF START ---
{diff}
--- DIFF END ---
"""

# ── 변경점 정리 에이전트 ────────────────────────────────

CHANGE_SUMMARY_PROMPT = """\
You are a technical writer creating a changelog summary.
Below is the COMPLETE diff containing ALL changed files.

Write a structured summary of what changed, in Korean, organized as:

1. **변경 개요** — 이 변경이 무엇을 하는지 2~3문장 요약
2. **파일별 변경사항** — 각 파일에 대해:
   - 파일명
   - 변경 유형 (신규/수정/삭제)
   - 주요 변경 내용 (함수/클래스 추가, 로직 변경 등)
3. **영향 범위** — 이 변경이 영향을 줄 수 있는 다른 모듈이나 기능

Rules:
- Do NOT review or critique the code. Only describe WHAT changed.
- Be factual and concise.

Title: {title}
Branch: {head_branch} → {base_branch}

--- DIFF START ---
{diff}
--- DIFF END ---
"""

# ── 리뷰 종합 에이전트 ─────────────────────────────────

SUMMARIZER_PROMPT = """\
You are a technical writer. Combine the following code review reports \
into a single, well-organized comment in Korean.

Format the output as markdown:
## 🐛 잠재적 버그
## 💡 개선 제안

- If a section has no issues, write "특이사항 없음".
- Keep total length under 400 words.
- Do NOT include the change summary here (it goes to a separate report).

---
Bug Review:
{bug_review}

Suggestion Review:
{suggestion_review}
"""

# ── 리포트 템플릿 (LLM 호출 없이 문자열 포맷팅) ────────

REPORT_TEMPLATE = """\
# Code Review Report

| 항목 | 내용 |
|------|------|
| 제목 | [{title}]({html_url}) |
| 작성자 | {author} |
| 브랜치 | `{head_branch}` → `{base_branch}` |
| 변경 파일 | {changed_files}개 ({additions}+ / {deletions}-) |

---

## 📋 변경점 요약

{change_summary}

---

## 🐛 잠재적 버그

{bug_review}

---

## 💡 개선 제안

{suggestion_review}

---

> 🤖 이 리포트는 AI Code Review Agent에 의해 자동 생성되었습니다.
"""
