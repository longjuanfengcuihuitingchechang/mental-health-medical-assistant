from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.repositories.work_assistant_repository import WorkAssistantRepository
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class PatientArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_user_id: str = Field(min_length=1, max_length=64)


class InventoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(default="", max_length=100)


class QueryTool:
    def __init__(self, name: str, description: str, roles: set[str], input_model, executor: Callable):
        self.name = name
        self.description = description
        self.allowed_roles = frozenset(roles)
        self.input_model = input_model
        self._executor = executor

    def execute(self, context: ToolContext, arguments: BaseModel) -> dict[str, Any]:
        return self._executor(context, arguments)


def build_work_tool_registry(repository: WorkAssistantRepository) -> ToolRegistry:
    registry = ToolRegistry()

    def my_schedule(ctx, _):
        rows = repository.query(
            """SELECT c.appointment_date, c.capacity,
                      (SELECT COUNT(*) FROM patient_appointments a WHERE a.doctor_user_id=c.doctor_user_id AND a.appointment_date=c.appointment_date AND a.status NOT IN ('cancelled','declined_direct','declined_gentle','change_requested')) AS appointment_count
               FROM doctor_daily_capacities c WHERE c.doctor_user_id=? ORDER BY c.appointment_date LIMIT 14""",
            (ctx.user_id,),
        )
        return {"items": rows, "count": len(rows)}

    def my_queue(ctx, _):
        rows = repository.query(
            """SELECT a.id AS appointment_id, a.appointment_date, a.queue_number,
                      a.status, u.display_name AS patient_display_name
               FROM patient_appointments a JOIN users u ON u.id=a.patient_user_id
               WHERE a.doctor_user_id=? AND a.status NOT IN ('cancelled','completed','declined_direct','declined_gentle','change_requested')
               ORDER BY a.appointment_date,a.queue_number LIMIT 100""",
            (ctx.user_id,),
        )
        return {"items": rows, "count": len(rows)}

    def visible_patient(ctx, args):
        if ctx.role == "doctor":
            scope = "EXISTS (SELECT 1 FROM patient_appointments a WHERE a.patient_user_id=u.id AND a.doctor_user_id=? )"
            params = (args.patient_user_id, ctx.user_id)
        else:
            scope = "EXISTS (SELECT 1 FROM patient_appointments a WHERE a.patient_user_id=u.id AND a.status IN ('awaiting_patient_decision','awaiting_doctor_decision'))"
            params = (args.patient_user_id,)
        rows = repository.query(
            f"SELECT u.id AS patient_user_id,u.display_name,p.medical_record_no FROM users u JOIN patient_profiles p ON p.user_id=u.id WHERE u.id=? AND {scope} LIMIT 1",
            params,
        )
        return {"item": rows[0] if rows else None}

    def doctor_schedule(_, args):
        rows = repository.query(
            """SELECT u.id AS doctor_user_id,u.display_name,d.department,d.professional_title,
                      d.employment_status,COALESCE(v.availability_status,'unknown') AS availability_status,
                      v.expected_available_at,c.capacity,
                      (SELECT COUNT(*) FROM patient_appointments a WHERE a.doctor_user_id=u.id AND a.appointment_date=? AND a.status NOT IN ('cancelled','declined_direct','declined_gentle','change_requested')) AS appointment_count
               FROM users u JOIN doctor_profiles d ON d.user_id=u.id
               LEFT JOIN doctor_availability v ON v.doctor_user_id=u.id
               LEFT JOIN doctor_daily_capacities c ON c.doctor_user_id=u.id AND c.appointment_date=?
               WHERE u.role='doctor' AND u.account_status='active' ORDER BY u.account""",
            (args.date, args.date),
        )
        return {"items": rows, "count": len(rows)}

    def coordination(_, __):
        rows = repository.query(
            """SELECT a.id AS appointment_id,a.appointment_date,a.queue_number,a.status,
                      p.display_name AS patient_display_name,d.display_name AS doctor_display_name
               FROM patient_appointments a JOIN users p ON p.id=a.patient_user_id JOIN users d ON d.id=a.doctor_user_id
               WHERE a.status IN ('awaiting_patient_decision','awaiting_doctor_decision')
               ORDER BY a.updated_at LIMIT 100"""
        )
        return {"items": rows, "count": len(rows)}

    def night_shift(_, args):
        rows = repository.query(
            "SELECT n.shift_date,n.doctor_user_id,u.display_name AS doctor_display_name FROM doctor_night_shifts n JOIN users u ON u.id=n.doctor_user_id WHERE n.shift_date=?",
            (args.date,),
        )
        return {"item": rows[0] if rows else None}

    def inventory(_, args):
        keyword = f"%{args.keyword.strip()}%"
        rows = repository.query(
            """SELECT medicine_name,specification,quantity,unit,batch_no_masked,expires_on,stock_status,source_updated_at
               FROM medicine_inventory WHERE medicine_name LIKE ? ORDER BY medicine_name LIMIT 50""",
            (keyword,),
        )
        return {"items": rows, "count": len(rows), "source_status": "available" if rows else "empty"}

    definitions = [
        ("get_my_schedule", "查询医生本人容量与预约数", {"doctor"}, EmptyArgs, my_schedule),
        ("get_my_appointment_queue", "查询医生本人预约队列", {"doctor"}, EmptyArgs, my_queue),
        ("get_visible_patient_summary", "查询当前角色可见患者最小摘要", {"doctor", "assistant"}, PatientArgs, visible_patient),
        ("get_doctor_schedule", "查询医生公开工作安排", {"assistant"}, DateArgs, doctor_schedule),
        ("get_coordination_queue", "查询助理协调队列", {"assistant"}, EmptyArgs, coordination),
        ("get_night_shift", "查询指定日期夜班", {"doctor", "assistant"}, DateArgs, night_shift),
        ("search_medicine_inventory", "只读查询药物库存摘要", {"doctor", "assistant"}, InventoryArgs, inventory),
    ]
    for definition in definitions:
        registry.register(QueryTool(*definition))
    return registry
