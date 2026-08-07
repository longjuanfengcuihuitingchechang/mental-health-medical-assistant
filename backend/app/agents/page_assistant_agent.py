from __future__ import annotations

from collections.abc import Callable

from app.schemas.page_assistant import (
    AssistantHistoryResponse,
    PageAssistantRequest,
    PageAssistantResponse,
)
from app.services.page_assistant_service import PatientPageAssistantService


class PatientPageAssistantAgent:
    """患者当前页说明、问答和就医导航 Agent。"""

    def __init__(self, service: PatientPageAssistantService):
        self.service = service

    def run(
        self,
        *,
        requester_user_id: str,
        request: PageAssistantRequest,
    ) -> PageAssistantResponse:
        return self.service.respond(
            patient_user_id=requester_user_id,
            request=request,
        )

    def run_stream(
        self,
        *,
        requester_user_id: str,
        request: PageAssistantRequest,
        on_delta: Callable[[str], None],
        should_stop: Callable[[], None],
    ) -> PageAssistantResponse:
        return self.service.respond(
            patient_user_id=requester_user_id,
            request=request,
            on_delta=on_delta,
            should_stop=should_stop,
        )

    def history(
        self,
        *,
        requester_user_id: str,
        session_id: str,
        limit: int = 50,
    ) -> AssistantHistoryResponse:
        return self.service.history(
            patient_user_id=requester_user_id,
            session_id=session_id,
            limit=limit,
        )
