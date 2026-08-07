from __future__ import annotations

from app.schemas.appointments import (
    AppointmentDecisionResponse,
    AppointmentResponse,
    CapacityRequest,
    CapacityResponse,
    CreateAppointmentRequest,
    DoctorDecisionRequest,
    NightShiftRequest,
    NightShiftResponse,
    PatientDecisionRequest,
    PendingAppointment,
)
from app.services.appointment_service import AppointmentService


class AppointmentCapacityAgent:
    def __init__(self, service: AppointmentService):
        self.service = service

    def run(self, *, requester_user_id: str, request: CapacityRequest) -> CapacityResponse:
        return self.service.set_capacity(doctor_user_id=requester_user_id, request=request)

    def summary(self, *, requester_user_id: str, doctor_user_id: str, appointment_date: str) -> dict:
        return self.service.summary(requester_user_id=requester_user_id, doctor_user_id=doctor_user_id, appointment_date=appointment_date)


class PatientAppointmentAgent:
    def __init__(self, service: AppointmentService):
        self.service = service

    def run(self, *, requester_user_id: str, request: CreateAppointmentRequest) -> AppointmentResponse:
        return self.service.create(patient_user_id=requester_user_id, request=request)

    def decide(self, *, requester_user_id: str, request: PatientDecisionRequest) -> AppointmentDecisionResponse:
        return self.service.patient_decide(patient_user_id=requester_user_id, request=request)


class AppointmentDecisionAgent:
    def __init__(self, service: AppointmentService):
        self.service = service

    def pending(self, *, requester_user_id: str) -> list[PendingAppointment]:
        return self.service.pending(requester_user_id=requester_user_id)

    def decide(self, *, requester_user_id: str, request: DoctorDecisionRequest) -> AppointmentDecisionResponse:
        return self.service.doctor_decide(doctor_user_id=requester_user_id, request=request)


class NightShiftAgent:
    def __init__(self, service: AppointmentService):
        self.service = service

    def run(self, *, requester_user_id: str, request: NightShiftRequest) -> NightShiftResponse:
        return self.service.assign_night_shift(requester_user_id=requester_user_id, request=request)

    def get(self, *, requester_user_id: str, shift_date: str) -> dict:
        return self.service.get_night_shift(requester_user_id=requester_user_id, shift_date=shift_date)
