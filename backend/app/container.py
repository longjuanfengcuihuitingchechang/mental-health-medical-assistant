from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.agents.admin_directory_agent import AdminDirectoryAgent
from app.agents.appointment_agent import (
    AppointmentCapacityAgent,
    AppointmentDecisionAgent,
    NightShiftAgent,
    PatientAppointmentAgent,
)
from app.agents.login_agent import LoginAgent
from app.agents.page_assistant_agent import PatientPageAssistantAgent
from app.agents.registration_agent import (
    DoctorRegistrationApprovalAgent,
    RegistrationAgent,
)
from app.agents.work_assistant_agent import WorkAssistantAgent
from app.core.config import Settings, settings
from app.core.identifiers import IdentifierProtector
from app.core.passwords import PasswordHasher
from app.db.connection import SQLiteConnectionFactory
from app.llm.base import BaseLLM, RuleBasedPageLLM
from app.llm.deepseek import DeepSeekLLM
from app.repositories.admin_directory_repository import AdminDirectoryRepository
from app.repositories.appointment_repository import AppointmentRepository
from app.repositories.login_repository import LoginRepository
from app.repositories.page_assistant_repository import PageAssistantRepository
from app.repositories.registration_repository import RegistrationRepository
from app.repositories.work_assistant_repository import WorkAssistantRepository
from app.services.admin_directory_service import AdminDirectoryService
from app.services.appointment_service import AppointmentService
from app.services.login_service import LoginService
from app.services.page_assistant_service import PatientPageAssistantService
from app.services.registration_service import (
    DoctorRegistrationApprovalService,
    RegistrationService,
)
from app.services.work_assistant_service import WorkAssistantService
from app.tools.work_tools import build_work_tool_registry


@dataclass(frozen=True, slots=True)
class ApplicationAgents:
    login: LoginAgent
    registration: RegistrationAgent
    doctor_registration_approval: DoctorRegistrationApprovalAgent
    admin_directory: AdminDirectoryAgent
    patient_page_assistant: PatientPageAssistantAgent
    appointment_capacity: AppointmentCapacityAgent
    patient_appointment: PatientAppointmentAgent
    appointment_decision: AppointmentDecisionAgent
    night_shift: NightShiftAgent
    work_assistant: WorkAssistantAgent


def build_application_agents(
    app_settings: Settings = settings,
    *,
    page_llm: BaseLLM | None = None,
) -> ApplicationAgents:
    database_path = app_settings.validated_database_path()
    protector = IdentifierProtector(app_settings.load_auth_pepper())
    password_hasher = PasswordHasher(
        iterations=app_settings.password_pbkdf2_iterations
    )
    connection_factory = SQLiteConnectionFactory(database_path)

    login_repository = LoginRepository(connection_factory)
    registration_repository = RegistrationRepository(
        connection_factory,
        protector,
    )
    directory_repository = AdminDirectoryRepository(connection_factory)
    page_assistant_repository = PageAssistantRepository(connection_factory)
    appointment_repository = AppointmentRepository(connection_factory)
    work_repository = WorkAssistantRepository(connection_factory)
    configured_page_llm = page_llm
    if configured_page_llm is None:
        deepseek_key = app_settings.load_deepseek_api_key()
        configured_page_llm = (
            DeepSeekLLM(
                api_key=deepseek_key,
                base_url=app_settings.deepseek_base_url,
                model=app_settings.deepseek_model,
                timeout_seconds=app_settings.deepseek_timeout_seconds,
            )
            if deepseek_key
            else RuleBasedPageLLM()
        )

    appointment_service = AppointmentService(
        appointment_repository,
        configured_page_llm,
    )

    return ApplicationAgents(
        login=LoginAgent(
            LoginService(
                login_repository,
                password_hasher,
                protector,
                max_attempts=app_settings.login_max_attempts,
                lock_duration=timedelta(
                    minutes=app_settings.login_lock_minutes
                ),
                session_duration=timedelta(hours=app_settings.session_hours),
            )
        ),
        registration=RegistrationAgent(
            RegistrationService(
                registration_repository,
                password_hasher,
                protector,
            )
        ),
        doctor_registration_approval=DoctorRegistrationApprovalAgent(
            DoctorRegistrationApprovalService(registration_repository)
        ),
        admin_directory=AdminDirectoryAgent(
            AdminDirectoryService(directory_repository)
        ),
        patient_page_assistant=PatientPageAssistantAgent(
            PatientPageAssistantService(
                page_assistant_repository,
                configured_page_llm,
            )
        ),
        appointment_capacity=AppointmentCapacityAgent(appointment_service),
        patient_appointment=PatientAppointmentAgent(appointment_service),
        appointment_decision=AppointmentDecisionAgent(appointment_service),
        night_shift=NightShiftAgent(appointment_service),
        work_assistant=WorkAssistantAgent(
            WorkAssistantService(
                work_repository,
                build_work_tool_registry(work_repository),
                configured_page_llm,
            )
        ),
    )
