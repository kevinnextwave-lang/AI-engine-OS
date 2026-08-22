import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AiGeneration, AiModel, AiProvider


class AiCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def provider_by_key(self, key: str) -> AiProvider | None:
        return (
            await self._session.scalars(select(AiProvider).where(AiProvider.provider_key == key))
        ).first()

    async def model_by_key(self, provider_id: uuid.UUID, model_key: str) -> AiModel | None:
        return (
            await self._session.scalars(
                select(AiModel).where(
                    AiModel.provider_id == provider_id, AiModel.model_key == model_key
                )
            )
        ).first()

    async def list_providers(self) -> list[AiProvider]:
        return list(
            (await self._session.scalars(select(AiProvider).order_by(AiProvider.name))).all()
        )

    async def list_models(self, provider_id: uuid.UUID | None = None) -> list[AiModel]:
        stmt = select(AiModel).order_by(AiModel.display_name)
        if provider_id is not None:
            stmt = stmt.where(AiModel.provider_id == provider_id)
        return list((await self._session.scalars(stmt)).all())

    async def add_generation(self, generation: AiGeneration) -> AiGeneration:
        self._session.add(generation)
        await self._session.flush()
        return generation

    async def get_generation(self, request_id: uuid.UUID) -> AiGeneration | None:
        return (
            await self._session.scalars(
                select(AiGeneration).where(AiGeneration.request_id == request_id)
            )
        ).first()
