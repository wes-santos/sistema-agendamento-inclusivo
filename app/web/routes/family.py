from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request
from fastapi.params import Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.db.session import get_db
from app.deps import require_roles
from app.models.user import Role, User
from app.web.templating import render

router = APIRouter()


def _render_family_dashboard(
    request: Request,
    current_user: User | None,
    db: Session | None,
    demo: bool = False,
) -> HTMLResponse:
    ctx = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        "next_appointment": None,
        "kpis": {
            "upcoming_30d": 0,
            "confirmed_30d": 0,
            "canceled_30d": 0,
            "total_month": 0,
            "month_label": "Este mês",
        },
        "recent_appointments": [],
        "recent_pagination": None,
    }

    if demo:
        ctx["next_appointment"] = {
            "id": "demo-1",
            "service_name": "Fonoaudiologia",
            "professional_name": "Dra. Ana",
            "starts_at_local": "14/09/2025 10:00",
            "ends_at_local": "14/09/2025 10:45",
            "starts_at_human": "Amanhã às 10:00",
            "location": "Sala 3",
            "status": "confirmed",
            "confirm_url": "/confirm/DEMO_TOKEN",
            "cancel_url": "/cancel/DEMO_TOKEN",
        }
        ctx["kpis"] = {
            "upcoming_30d": 3,
            "confirmed_30d": 5,
            "canceled_30d": 1,
            "total_month": 7,
            "month_label": "Setembro",
        }
        ctx["recent_appointments"] = [
            {
                "id": "r1",
                "service_name": "Psicopedagogia",
                "professional_name": "Marcos",
                "starts_at_local": "12/09/2025 09:00",
                "status": "scheduled",
                "cancel_url": "/cancel/DEMO_TOKEN_R1",
            },
            {
                "id": "r2",
                "service_name": "Neuropsicologia",
                "professional_name": "Carla",
                "starts_at_local": "10/09/2025 14:00",
                "status": "canceled",
                "cancel_url": None,
            },
        ]

    return render(request, "pages/family/dashboard.html", ctx)


def _demo_family_appts(base: datetime):
    base = base.replace(hour=10, minute=0, second=0, microsecond=0)
    items = [
        {
            "id": "a1",
            "service_name": "Psicopedagogia",
            "professional_name": "Marcos",
            "starts_at_local": (base - timedelta(days=2)).strftime("%d/%m/%Y %H:%M"),
            "ends_at_local": (
                base - timedelta(days=2) + timedelta(minutes=45)
            ).strftime("%d/%m/%Y %H:%M"),
            "status": "scheduled",
            "location": "Sala 1",
            "confirm_url": "/family/appointments/a1/confirm",
            "cancel_url": "/family/appointments/a1/cancel",
        },
        {
            "id": "a2",
            "service_name": "Neuropsicologia",
            "professional_name": "Carla",
            "starts_at_local": (base - timedelta(days=4)).strftime("%d/%m/%Y %H:%M"),
            "ends_at_local": (
                base - timedelta(days=4) + timedelta(minutes=45)
            ).strftime("%d/%m/%Y %H:%M"),
            "status": "canceled",
            "location": "Sala 3",
            "confirm_url": None,
            "cancel_url": None,
        },
    ]
    return items


# LISTA
@router.get(
    "/family/appointments", response_class=HTMLResponse, name="family_appointments"
)
def ui_family_appointments(
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    demo: bool = Query(False),
):
    # TODO: troque por query real
    appts = _demo_family_appts(datetime.now()) if demo else []
    ctx = {
        "appointments": appts,
        "filters": {},
        "pagination": None,
    }
    return render(request, "pages/family/appointments.html", ctx)


# DETALHE
@router.get(
    "/family/appointments/{appt_id}",
    response_class=HTMLResponse,
    name="family_appointment_detail",
)
def ui_family_appointment_detail(
    appt_id: str,
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    demo: bool = Query(False),
):
    # TODO: troque por busca real
    appts = _demo_family_appts(datetime.now()) if demo else []
    appt = next((a for a in appts if a["id"] == appt_id), None)
    if not appt:
        # Pode renderizar um empty_state elegante, mas por simplicidade:
        return render(
            request,
            "components/empty_state.html",
            {
                "title": "Agendamento não encontrado",
                "message": "Verifique o link ou acesse seus agendamentos.",
                "actions_html": '<a class="btn" href="/family/appointments">Ver meus agendamentos</a>',
                "icon": "🔎",
                "size": "md",
            },
        )

    return render(
        request, "pages/family/appointment_detail.html", {"appointment": appt}
    )


@router.get("/__dev/family/dashboard", response_class=HTMLResponse)
def preview_family_dashboard(request: Request, demo: bool = True):
    # Reusa a lógica acima mas sem require_roles
    return _render_family_dashboard(request, current_user=None, db=None, demo=demo)


@router.get("/family/dashboard", response_class=HTMLResponse)
def ui_family_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(Role.FAMILY)),
    db: Session = Depends(get_db),
    demo: bool = False,  # ?demo=1 para ver conteúdo fake
):
    """
    Renderiza o dashboard da Família.
    Preenchemos só o mínimo p/ tela subir; com ?demo=1 injeta dados fake p/ visualizar.
    """
    ctx = {
        "request": request,
        "current_user": current_user,
        "app_version": getattr(settings, "APP_VERSION", "dev"),
        # valores vazios são OK — a página mostra empty states
        "next_appointment": None,
        "kpis": {
            "upcoming_30d": 0,
            "confirmed_30d": 0,
            "canceled_30d": 0,
            "total_month": 0,
            "month_label": "Este mês",
        },
        "recent_appointments": [],
        "recent_pagination": None,
    }

    if demo:
        # Dados fake só para validar o visual rapidamente
        ctx["next_appointment"] = {
            "id": "demo-1",
            "service_name": "Fonoaudiologia",
            "professional_name": "Dra. Ana",
            "starts_at_local": "14/09/2025 10:00",
            "ends_at_local": "14/09/2025 10:45",
            "starts_at_human": "Amanhã às 10:00",
            "location": "Sala 3",
            "status": "confirmed",
            "confirm_url": "/confirm/DEMO_TOKEN",
            "cancel_url": "/cancel/DEMO_TOKEN",
        }
        ctx["kpis"] = {
            "upcoming_30d": 3,
            "confirmed_30d": 5,
            "canceled_30d": 1,
            "total_month": 7,
            "month_label": "Setembro",
        }
        ctx["recent_appointments"] = [
            {
                "id": "r1",
                "service_name": "Psicopedagogia",
                "professional_name": "Marcos",
                "starts_at_local": "12/09/2025 09:00",
                "status": "scheduled",
                "cancel_url": "/cancel/DEMO_TOKEN_R1",
            },
            {
                "id": "r2",
                "service_name": "Neuropsicologia",
                "professional_name": "Carla",
                "starts_at_local": "10/09/2025 14:00",
                "status": "canceled",
                "cancel_url": None,
            },
        ]

    return render(request, "pages/family/dashboard.html", ctx)
