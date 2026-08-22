from fastapi import APIRouter

from app.api.v1.routes import auth, crawl, health, organizations, projects

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(projects.org_router)
api_router.include_router(projects.router)
api_router.include_router(crawl.project_router)
api_router.include_router(crawl.router)
