from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    crawl,
    entities,
    health,
    organizations,
    pages,
    projects,
    seo,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.org_router)
api_router.include_router(projects.router)
api_router.include_router(crawl.project_router)
api_router.include_router(crawl.router)
api_router.include_router(pages.project_router)
api_router.include_router(pages.router)
api_router.include_router(seo.project_router)
api_router.include_router(seo.router)
api_router.include_router(entities.project_router)
api_router.include_router(entities.page_router)
