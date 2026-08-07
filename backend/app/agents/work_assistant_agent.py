from collections.abc import Callable

from app.schemas.work_assistant import WorkAssistantRequest, WorkAssistantResponse
from app.services.work_assistant_service import WorkAssistantService


class WorkAssistantAgent:
    def __init__(self, service: WorkAssistantService):
        self.service = service

    def run(self, *, requester_user_id: str, role: str, request: WorkAssistantRequest) -> WorkAssistantResponse:
        return self.service.respond(requester_user_id, role, request)

    def run_stream(
        self,
        *,
        requester_user_id: str,
        role: str,
        request: WorkAssistantRequest,
        on_delta: Callable[[str], None],
        should_stop: Callable[[], None],
    ) -> WorkAssistantResponse:
        return self.service.respond(
            requester_user_id,
            role,
            request,
            on_delta=on_delta,
            should_stop=should_stop,
        )
