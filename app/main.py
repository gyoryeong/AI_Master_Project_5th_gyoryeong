"""
FastAPI 애플리케이션 엔트리포인트.

실행 방법:
    uvicorn app.main:app --reload        # 개발
    uvicorn app.main:app --host 0.0.0.0  # 운영
"""

import logging

from fastapi import FastAPI

from app.config import settings
from app.webhook import router

# 로깅 설정
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# FastAPI 앱 생성
app = FastAPI(
    title="Code Review Agent",
    description="LangChain + LangGraph 기반 Multi-Agent AI 코드 리뷰 봇",
    version="0.3.0",
)

# 웹훅 라우터 등록
app.include_router(router)


@app.get("/health")
async def health():
    """헬스체크 엔드포인트. 배포 환경에서 서버 상태 확인용."""
    return {"status": "ok", "version": "0.3.0"}
