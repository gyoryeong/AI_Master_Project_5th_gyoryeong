# Code Review Agent v0.3

LangChain + LangGraph 기반 **Multi-Agent AI 코드 리뷰 봇**.
GitHub PR 생성 또는 Push 시 자동으로 코드 리뷰를 수행하고,
리포트를 생성하여 코멘트 + 이메일로 전달합니다.

---

## 목차..

1. [주요 기능](#주요-기능)
2. [Multi-Agent 구조](#multi-agent-구조)
3. [프로젝트 구조](#프로젝트-구조)
4. [빠른 시작](#빠른-시작)
5. [환경변수 설정](#환경변수-설정)
6. [GitHub Webhook 설정](#github-webhook-설정)
7. [지원 이벤트 및 페이로드](#지원-이벤트-및-페이로드)
8. [로컬 테스트 (ngrok)](#로컬-테스트-ngrok)
9. [Docker 배포](#docker-배포)
10. [향후 고도화 방향](#향후-고도화-방향)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| **PR 자동 리뷰** | PR 생성(opened) 시 버그 탐지 + 개선 제안을 PR 코멘트로 게시 |
| **Push 자동 리뷰** | 대상 브랜치에 push 시 커밋 코멘트로 리뷰 게시 |
| **변경점 문서화** | 리뷰와 별개로 소스코드 변경사항을 한국어로 정리 요약 |
| **리포트 생성** | 리뷰 결과 + 변경점 요약을 `.md` 파일로 생성 |
| **이메일 발송** | 리포트를 팀에게 자동 메일링 (SMTP) |
| **LLM 비용 최소화** | 전체 diff 병합 후 에이전트당 1회 호출 — 파일 수 무관 총 4회 |

---

## Multi-Agent 구조

```
merge_diff          ← 전체 파일 diff를 1개 텍스트로 병합 (LLM 0회)
    │
    ├─ Bug Reviewer          ← LLM 1회 (전체 diff 대상)
    ├─ Suggestion Reviewer   ← LLM 1회 (전체 diff 대상)
    └─ Change Summarizer     ← LLM 1회 (전체 diff 대상)
          │
      Summarize Review       ← LLM 1회 (3개 결과 종합)
          │
      Generate Report        ← 템플릿 채우기 (LLM 0회)
          │
      ├─ PR/커밋 코멘트 게시
      ├─ .md 리포트 저장
      └─ 이메일 발송
```

**비용 비교** (파일 10개 PR 기준):
- 파일별 호출 방식: 10 × 3 에이전트 = **30회** LLM 호출
- 병합 호출 방식: **4회** LLM 호출 (merge 후 에이전트당 1회 + 종합 1회)

---

## 프로젝트 구조

```
code-review-agent/
├── app/
│   ├── main.py              # FastAPI 엔트리포인트 + 헬스체크
│   ├── config.py            # pydantic-settings 환경변수 관리
│   ├── models.py            # GitHub Webhook 페이로드 Pydantic 모델
│   │                        #   - PullRequestEvent (PR 이벤트)
│   │                        #   - PushEvent (Push 이벤트)
│   ├── webhook.py           # Webhook 수신 → 시그니처 검증 → 이벤트 라우팅
│   │                        #   - pull_request 핸들러
│   │                        #   - push 핸들러
│   │                        #   - ping 핸들러
│   ├── github_service.py    # GitHub REST API 연동
│   │                        #   - fetch_pr_diff (페이지네이션)
│   │                        #   - fetch_push_diff (compare API)
│   │                        #   - post_pr_comment / post_commit_comment
│   ├── email_service.py     # SMTP 비동기 이메일 발송
│   └── agents/
│       ├── state.py         # LangGraph 공유 상태 (TypedDict)
│       ├── prompts.py       # 에이전트별 프롬프트 + 리포트 템플릿
│       └── graph.py         # LangGraph StateGraph 워크플로우 빌드
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## 빠른 시작

### 사전 요구사항

- Python 3.11+
- GitHub Personal Access Token (`repo` 스코프)
- Anthropic API Key

### 설치 및 실행

```bash
# 1. 클론
git clone <repository-url>
cd code-review-agent

# 2. 환경변수 설정
cp .env.example .env
# .env 파일을 열어 실제 토큰 입력

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 서버 실행
uvicorn app.main:app --reload --port 8000

# 5. 헬스체크 확인
curl http://localhost:8000/health
# → {"status":"ok","version":"0.3.0"}
```

---

## 환경변수 설정

`.env.example`을 `.env`로 복사한 뒤 값을 입력합니다.

| 변수명 | 필수 | 설명 |
|--------|------|------|
| `GITHUB_WEBHOOK_SECRET` | 권장 | Webhook 시그니처 검증용 시크릿 |
| `GITHUB_TOKEN` | **필수** | GitHub PAT (repo 스코프) |
| `ANTHROPIC_API_KEY` | **필수** | Claude API 키 |
| `TARGET_EXTENSIONS` | 선택 | 리뷰 대상 확장자 (기본: `.py`) |
| `MAX_DIFF_LINES` | 선택 | 파일당 최대 diff 줄 수 (기본: `500`) |
| `TARGET_BRANCHES` | 선택 | Push 리뷰 대상 브랜치 (기본: `main,develop`) |
| `SMTP_HOST` | 선택 | SMTP 서버 (기본: `smtp.gmail.com`) |
| `SMTP_PORT` | 선택 | SMTP 포트 (기본: `587`) |
| `SMTP_USER` | 선택 | SMTP 로그인 이메일 |
| `SMTP_PASSWORD` | 선택 | SMTP 비밀번호 (Gmail: 앱 비밀번호) |
| `MAIL_RECIPIENTS` | 선택 | 수신자 목록 (쉼표 구분) |
| `REPORT_OUTPUT_DIR` | 선택 | 리포트 저장 경로 (기본: `/tmp/reports`) |

---

## GitHub Webhook 설정

### 1단계: Repository Settings

1. GitHub 리포지토리 → **Settings** → **Webhooks** → **Add webhook**
2. 설정 값 입력:

| 항목 | 값 |
|------|------|
| Payload URL | `https://<your-domain>/webhook` |
| Content type | `application/json` |
| Secret | `.env`의 `GITHUB_WEBHOOK_SECRET` 값 |

### 2단계: 이벤트 선택

**"Let me select individual events"** 를 선택하고:
- ✅ **Pull requests** — PR 생성/업데이트 시 리뷰
- ✅ **Pushes** — 브랜치 push 시 리뷰

### 3단계: 연결 확인

웹훅 등록 시 GitHub가 자동으로 `ping` 이벤트를 전송합니다.
서버 로그에 `Ping 이벤트 수신` 메시지가 나타나면 정상입니다.

---

## 지원 이벤트 및 페이로드

### pull_request 이벤트

GitHub가 PR 관련 활동 시 전송합니다.

**HTTP 요청:**
```
POST /webhook HTTP/1.1
X-GitHub-Event: pull_request
X-Hub-Signature-256: sha256=d57c68ca6f92289e...
X-GitHub-Delivery: 72d3162e-cc78-11e3-81ab-4c9367dc0958
Content-Type: application/json
```

**페이로드 (주요 필드):**
```json
{
  "action": "opened",
  "number": 42,
  "pull_request": {
    "number": 42,
    "title": "Add login feature",
    "html_url": "https://github.com/owner/repo/pull/42",
    "user": { "login": "octocat" },
    "head": { "ref": "feature/login", "sha": "abc123" },
    "base": { "ref": "main", "sha": "def456" },
    "commits": 3,
    "additions": 150,
    "deletions": 30,
    "changed_files": 5
  },
  "repository": {
    "id": 1296269,
    "full_name": "octocat/Hello-World"
  },
  "sender": { "login": "octocat" }
}
```

**처리 조건:** `action == "opened"` 인 경우에만 리뷰 실행.

### push 이벤트

브랜치에 커밋 push 시 전송됩니다. **`action` 필드가 없습니다.**

**HTTP 요청:**
```
POST /webhook HTTP/1.1
X-GitHub-Event: push
X-Hub-Signature-256: sha256=7d38cdd689735b...
Content-Type: application/json
```

**페이로드 (주요 필드):**
```json
{
  "ref": "refs/heads/main",
  "before": "abc123def456...",
  "after": "789ghi012jkl...",
  "created": false,
  "deleted": false,
  "forced": false,
  "compare": "https://github.com/owner/repo/compare/abc123...789ghi",
  "commits": [
    {
      "id": "789ghi012jkl...",
      "message": "Fix login bug",
      "author": {
        "name": "Ozer",
        "email": "ozer@example.com",
        "username": "ozers"
      },
      "added": ["src/auth.py"],
      "modified": ["src/login.py"],
      "removed": []
    }
  ],
  "head_commit": {
    "id": "789ghi012jkl...",
    "message": "Fix login bug"
  },
  "repository": {
    "full_name": "octocat/Hello-World"
  },
  "pusher": { "name": "octocat", "email": "octocat@github.com" },
  "sender": { "login": "octocat" }
}
```

**처리 조건:**
- `deleted == false` (브랜치 삭제가 아닌 경우)
- 브랜치가 `TARGET_BRANCHES`에 포함된 경우

### ping 이벤트

웹훅 최초 등록 시 GitHub가 자동 전송합니다.
서버는 `{"status": "pong"}`으로 응답합니다.

---

## 로컬 테스트 (ngrok)

GitHub webhook은 퍼블릭 URL이 필요합니다.
로컬 개발 시 ngrok으로 터널을 열어 테스트합니다.

```bash
# 1. 서버 실행
uvicorn app.main:app --reload --port 8000

# 2. 다른 터미널에서 ngrok 실행
ngrok http 8000

# 3. ngrok 출력에서 https URL 복사
# Forwarding  https://xxxx-xx-xx.ngrok.io → http://localhost:8000

# 4. GitHub webhook Payload URL에 입력
# https://xxxx-xx-xx.ngrok.io/webhook
```

**테스트 방법:**
1. 테스트 브랜치 생성 → PR 생성 → PR 코멘트 확인
2. 대상 브랜치에 commit push → 커밋 코멘트 확인
3. GitHub Webhooks 페이지 → **Recent Deliveries** 에서 요청/응답 확인

---

## Docker 배포

```bash
# 빌드
docker build -t code-review-agent .

# 실행
docker run -d \
  -p 8000:8000 \
  --env-file .env \
  --name code-review-agent \
  code-review-agent

# 로그 확인
docker logs -f code-review-agent
```

### Railway / Render 배포

1. GitHub 리포지토리를 연결
2. 환경변수를 대시보드에서 설정
3. Dockerfile 기반 자동 빌드/배포

---

## 시퀀스 다이어그램

```
PR 생성 (opened)
─────────────────────────────────────────────────

  GitHub          Server              LLM API
    │                │                   │
    ├─ webhook ──→   │                   │
    │  (PR payload)  │                   │
    │                ├─ verify sig       │
    │                ├─ parse payload    │
    │                ├─ GET /pulls/files │
    │   ←────────────┤  (paginated)     │
    │                │                   │
    │                ├─ merge_diff       │
    │                ├─ bug review ──→   │
    │                │       ←───── resp │
    │                ├─ suggestion ──→   │
    │                │       ←───── resp │
    │                ├─ change sum ──→   │
    │                │       ←───── resp │
    │                ├─ summarize ───→   │
    │                │       ←───── resp │
    │                ├─ generate report  │
    │                │                   │
    │   ←── POST comment ──┤             │
    │                ├─ send email       │
    │                │                   │

Push (to main)
─────────────────────────────────────────────────

  GitHub          Server              LLM API
    │                │                   │
    ├─ webhook ──→   │                   │
    │  (push payload)│                   │
    │                ├─ verify sig       │
    │                ├─ parse payload    │
    │                ├─ check branch     │
    │                ├─ GET /compare     │
    │   ←────────────┤  (before...after) │
    │                │                   │
    │                ├─ (동일 리뷰 흐름)  │
    │                │                   │
    │   ←── POST commit comment ─┤       │
    │                ├─ send email       │
```

---

## 향후 고도화 방향

1. **PR synchronize 이벤트** — 커밋 추가 시 자동 재리뷰
2. **Line-level inline comment** — 파일의 특정 라인에 직접 코멘트
3. **멀티 언어 지원** — `.js`, `.ts`, `.java`, `.go` 등
4. **LangGraph 병렬 실행** — Send API로 3개 에이전트 동시 실행 (3배 속도)
5. **RAG 기반 컨벤션 참조** — 프로젝트 코딩 가이드 문서를 벡터 DB에 저장
6. **리뷰 품질 피드백** — 👍👎 반응으로 프롬프트 자동 튜닝
7. **Slack / Teams 알림** — 이메일 외 추가 알림 채널

---

## 참고 문서

- [GitHub Webhook Events and Payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
- [GitHub REST API — Pull Request Files](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files)
- [GitHub REST API — Compare Commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Anthropic Integration](https://python.langchain.com/docs/integrations/chat/anthropic)
#   A I _ M a s t e r _ P r o j e c t _ 5 t h _ g y o r y e o n g 
 
 #   A I _ M a s t e r _ P r o j e c t _ 5 t h _ g y o r y e o n g 
 
 #   A I _ M a s t e r _ P r o j e c t _ 5 t h _ g y o r y e o n g 
 
 #   A I _ M a s t e r _ P r o j e c t _ 5 t h _ g y o r y e o n g 
 
 