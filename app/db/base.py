# Garante o registro de TODAS as models no mesmo registry
from app.db.base_class import Base # noqa
from app.models.appointment import Appointment # noqa
from app.models.audit_log import AuditLog # noqa
from app.models.availability import Availability # noqa
from app.models.professional import Professional # noqa
from app.models.student import Student # noqa

# IMPORTS com efeito colateral (não remova)
from app.models.user import User # noqa
