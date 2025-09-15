from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.core.settings import settings

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.add_extension("jinja2.ext.do")

# Globais/filters comuns a TODO o app
templates.env.globals.update(
    {
        "app_version": getattr(settings, "APP_VERSION", "dev"),
    }
)


# Helpers para usar nos routers
def get_templates() -> Jinja2Templates:
    """Dependency opcional (caso prefira Depends)."""
    return templates


def render(request, name: str, context: dict):
    """Atalho: garante 'request' no contexto e retorna TemplateResponse."""
    context.setdefault("request", request)
    return templates.TemplateResponse(name, context)
