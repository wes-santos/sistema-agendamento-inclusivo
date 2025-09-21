"""API router setup."""
from fastapi import APIRouter

from app.api.v1 import (
    appointments_wizard,
    auth,
    availability,
    dashboard_coordination,
    dashboard_family,
    dashboard_professional,
    professionals,
    slots,
    students,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(appointments_wizard.router)
api_router.include_router(availability.router)
api_router.include_router(dashboard_coordination.router)
api_router.include_router(dashboard_family.router)
api_router.include_router(dashboard_professional.router)
api_router.include_router(professionals.router)
api_router.include_router(slots.router)
api_router.include_router(students.router)