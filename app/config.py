"""
환경변수 설정 모듈.

pydantic-settings를 사용하여 .env 파일과 OS 환경변수를 자동으로 읽어온다.
모든 설정값은 Settings 인스턴스를 통해 접근한다.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── GitHub 연동 ──────────────────────────────────────
    # Webhook 시그니처 검증용 시크릿 (빈 문자열이면 검증 건너뜀 — 개발용)
    github_webhook_secret: str = ""
    # GitHub REST API 호출용 Personal Access Token
    github_token: str = ""

    # ── LLM ──────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── 리뷰 대상 필터 ──────────────────────────────────
    # 쉼표 구분 확장자 목록. 예: ".py,.js,.ts"
    target_extensions: str = ".py"
    # 파일당 최대 diff 줄 수. 초과분은 잘린다.
    max_diff_lines: int = 500

    # ── Push 이벤트 설정 ────────────────────────────────
    # push 이벤트에서 리뷰할 브랜치 목록 (쉼표 구분)
    # refs/heads/main → "main"으로 매칭
    target_branches: str = "main,develop"

    # ── 이메일 (SMTP) ──────────────────────────────────
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # 수신자 목록 (쉼표 구분)
    mail_recipients: str = ""

    # ── 리포트 ──────────────────────────────────────────
    report_output_dir: str = "/tmp/reports"

    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# 전역 싱글턴 인스턴스
settings = Settings()
