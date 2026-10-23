from fastapi import APIRouter

from app.api.v1 import health
from app.modules.assistant.router import router as assistant_router
from app.modules.audit.router import router as audit_router
from app.modules.billing.router import invoices_router, payments_router, quotations_router
from app.modules.clients.router import router as clients_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.documents.router import (
    documents_router,
    rab_documents_router,
    settings_router,
)
from app.modules.identity.router import auth_router, org_router, roles_router, users_router
from app.modules.intake.router import router as intake_router
from app.modules.pricing.router import (
    catalog_router,
    observations_router,
    sources_router,
    suppliers_router,
)
from app.modules.projects.router import router as projects_router
from app.modules.rab.import_router import router as rab_import_router
from app.modules.rab.router import approvals_router
from app.modules.rab.router import project_router as project_rab_router
from app.modules.rab.router import router as rab_router
from app.modules.workorders.router import bast_router, spk_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth_router)
api_router.include_router(org_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(clients_router)
api_router.include_router(projects_router)
api_router.include_router(project_rab_router)
api_router.include_router(rab_import_router)
api_router.include_router(rab_router)
api_router.include_router(approvals_router)
api_router.include_router(rab_documents_router)
api_router.include_router(documents_router)
api_router.include_router(settings_router)
api_router.include_router(quotations_router)
api_router.include_router(invoices_router)
api_router.include_router(payments_router)
api_router.include_router(spk_router)
api_router.include_router(bast_router)
api_router.include_router(assistant_router)
api_router.include_router(intake_router)
api_router.include_router(suppliers_router)
api_router.include_router(catalog_router)
api_router.include_router(observations_router)
api_router.include_router(sources_router)
api_router.include_router(audit_router)
api_router.include_router(dashboard_router)
