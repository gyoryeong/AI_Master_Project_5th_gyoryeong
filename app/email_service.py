"""
이메일 발송 서비스.

aiosmtplib를 사용하여 SMTP 비동기 발송을 수행한다.
리뷰 리포트(.md)를 첨부파일로 포함하여 팀에게 자동 메일링한다.
"""

import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib

from app.config import settings

logger = logging.getLogger(__name__)


async def send_report_email(
    subject: str,
    body_text: str,
    attachment_path: Path | None = None,
) -> None:
    """리뷰 리포트를 이메일로 발송한다.

    Args:
        subject: 이메일 제목. 예: "[Code Review] Fix login bug (#42)"
        body_text: 이메일 본문 텍스트 (간단 요약)
        attachment_path: 첨부할 .md 리포트 파일 경로 (없으면 본문만 전송)

    설정 미비 시 경고 로그만 남기고 조용히 건너뛴다.
    (파일럿 단계에서 이메일 미설정이 일반적이므로 예외를 던지지 않음)
    """
    # 수신자 파싱
    recipients = [r.strip() for r in settings.mail_recipients.split(",") if r.strip()]
    if not recipients:
        logger.warning("MAIL_RECIPIENTS 미설정 — 이메일 발송 건너뜀")
        return

    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("SMTP 인증정보 미설정 — 이메일 발송 건너뜀")
        return

    # 이메일 메시지 구성
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_text)

    # .md 파일 첨부
    if attachment_path and attachment_path.exists():
        content = attachment_path.read_bytes()
        msg.add_attachment(
            content,
            maintype="text",
            subtype="markdown",
            filename=attachment_path.name,
        )
        logger.info("리포트 파일 첨부: %s", attachment_path.name)

    # SMTP 발송
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info("이메일 발송 완료 → %s", recipients)
    except Exception:
        logger.exception("이메일 발송 실패")
