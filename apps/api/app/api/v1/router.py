from fastapi import APIRouter

from app.api.v1.routes import (
    ai_readiness,
    auth,
    crawl,
    entities,
    execution,
    health,
    intelligence,
    organizations,
    pages,
    projects,
    prompts,
    seo,
    visibility,
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
api_router.include_router(ai_readiness.project_router)
api_router.include_router(ai_readiness.router)
api_router.include_router(prompts.project_router)
api_router.include_router(prompts.set_router)
api_router.include_router(prompts.prompt_router)
api_router.include_router(execution.providers_router)
api_router.include_router(execution.set_router)
api_router.include_router(execution.batch_router)
api_router.include_router(execution.prompt_router)
api_router.include_router(intelligence.run_router)
api_router.include_router(intelligence.batch_router)
api_router.include_router(visibility.router)
