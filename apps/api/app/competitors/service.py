"""Competitor configuration: CRUD with duplicate handling, aliases, domains, products.

Duplicates are rejected by normalised domain, normalised name, and by any
alias/product name that already identifies another competitor of the same
project (a competitor's own site is not a competitor either). Every lookup
is scoped to the project, so rows of other tenants are never reachable here.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.competitors.normalize import normalize_name
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.urls import InvalidURLError, normalize_website_url
from app.models.competitor import (
    Competitor,
    CompetitorAlias,
    CompetitorConfidence,
    CompetitorDomain,
    CompetitorDomainType,
    CompetitorProduct,
    CompetitorSource,
    CompetitorStatus,
)
from app.models.domain import Domain
from app.sources.normalize import normalize_hostname


@dataclass
class CompetitorInput:
    name: str
    website_url: str
    description: str | None = None
    source: CompetitorSource = CompetitorSource.MANUAL
    status: CompetitorStatus = CompetitorStatus.ACTIVE
    confidence: CompetitorConfidence = CompetitorConfidence.HIGH
    aliases: list[str] | None = None


class CompetitorService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- queries ---------------------------------------------------------------------

    def _loaded(self) -> Select[tuple[Competitor]]:
        return select(Competitor).options(
            selectinload(Competitor.aliases),
            selectinload(Competitor.domains),
            selectinload(Competitor.products),
        )

    async def list_for_project(
        self, project_id: uuid.UUID, *, status: CompetitorStatus | None = None
    ) -> list[Competitor]:
        stmt = self._loaded().where(Competitor.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Competitor.status == status.value)
        return list((await self._session.scalars(stmt.order_by(Competitor.created_at))).all())

    async def get(self, competitor_id: uuid.UUID) -> Competitor | None:
        """Unscoped lookup — callers must check project access on the result."""
        return (
            await self._session.scalars(self._loaded().where(Competitor.id == competitor_id))
        ).first()

    async def get_in_project(self, project_id: uuid.UUID, competitor_id: uuid.UUID) -> Competitor:
        row = (
            await self._session.scalars(
                self._loaded().where(
                    Competitor.id == competitor_id, Competitor.project_id == project_id
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("Competitor not found")
        return row

    # -- duplicate handling ------------------------------------------------------------------

    async def _identity_taken(
        self, project_id: uuid.UUID, normalized: str, *, exclude: uuid.UUID | None = None
    ) -> Competitor | None:
        """The project's competitor already identified by this normalised name/alias/product."""
        if not normalized:
            return None
        by_name = select(Competitor).where(
            Competitor.project_id == project_id, Competitor.normalized_name == normalized
        )
        by_alias = (
            select(Competitor)
            .join(CompetitorAlias, CompetitorAlias.competitor_id == Competitor.id)
            .where(
                Competitor.project_id == project_id, CompetitorAlias.normalized_alias == normalized
            )
        )
        by_product = (
            select(Competitor)
            .join(CompetitorProduct, CompetitorProduct.competitor_id == Competitor.id)
            .where(
                Competitor.project_id == project_id, CompetitorProduct.normalized_name == normalized
            )
        )
        for stmt in (by_name, by_alias, by_product):
            if exclude is not None:
                stmt = stmt.where(Competitor.id != exclude)
            hit = (await self._session.scalars(stmt)).first()
            if hit is not None:
                return hit
        return None

    async def _domain_taken(
        self, project_id: uuid.UUID, normalized_domain: str, *, exclude: uuid.UUID | None = None
    ) -> Competitor | None:
        stmt = select(Competitor).where(
            Competitor.project_id == project_id, Competitor.normalized_domain == normalized_domain
        )
        if exclude is not None:
            stmt = stmt.where(Competitor.id != exclude)
        hit = (await self._session.scalars(stmt)).first()
        if hit is not None:
            return hit
        stmt = (
            select(Competitor)
            .join(CompetitorDomain, CompetitorDomain.competitor_id == Competitor.id)
            .where(
                Competitor.project_id == project_id, CompetitorDomain.domain == normalized_domain
            )
        )
        if exclude is not None:
            stmt = stmt.where(Competitor.id != exclude)
        return (await self._session.scalars(stmt)).first()

    async def _is_own_domain(self, project_id: uuid.UUID, normalized_domain: str) -> bool:
        rows = (
            await self._session.scalars(
                select(Domain.hostname).where(Domain.project_id == project_id)
            )
        ).all()
        return any(normalize_hostname(h) == normalized_domain for h in rows)

    # -- competitor CRUD ------------------------------------------------------------------------

    async def create(self, project_id: uuid.UUID, data: CompetitorInput) -> Competitor:
        try:
            normalized_url = normalize_website_url(data.website_url)
        except InvalidURLError as exc:
            raise ValidationAppError(str(exc)) from exc
        normalized_domain = normalize_hostname(normalized_url.hostname) or normalized_url.hostname
        name = data.name.strip()
        normalized_name = normalize_name(name)
        if not normalized_name:
            raise ValidationAppError("Competitor name must contain letters or digits")
        if await self._is_own_domain(project_id, normalized_domain):
            raise ConflictError(
                f"{normalized_domain} is one of this project's own domains, not a competitor"
            )
        if dup := await self._domain_taken(project_id, normalized_domain):
            raise ConflictError(f"Competitor {normalized_domain} is already tracked as {dup.name}")
        if dup := await self._identity_taken(project_id, normalized_name):
            raise ConflictError(f"'{name}' already identifies competitor {dup.name}")
        competitor = Competitor(
            project_id=project_id,
            name=name,
            normalized_name=normalized_name,
            website_url=normalized_url.url,
            hostname=normalized_url.hostname,
            normalized_domain=normalized_domain,
            description=(data.description or "").strip() or None,
            source=data.source.value,
            status=data.status.value,
            confidence=data.confidence.value,
        )
        competitor.domains.append(
            CompetitorDomain(
                domain=normalized_domain,
                domain_type=CompetitorDomainType.PRIMARY.value,
                is_primary=True,
            )
        )
        self._session.add(competitor)
        await self._session.flush()
        competitor = await self.get_in_project(project_id, competitor.id)
        for alias in data.aliases or []:
            await self.add_alias(competitor, alias)
        return competitor

    async def update(
        self,
        competitor: Competitor,
        *,
        name: str | None = None,
        website_url: str | None = None,
        description: str | None = None,
        clear_description: bool = False,
        status: CompetitorStatus | None = None,
        confidence: CompetitorConfidence | None = None,
    ) -> Competitor:
        pid = competitor.project_id
        if name is not None and name.strip() != competitor.name:
            normalized_name = normalize_name(name)
            if not normalized_name:
                raise ValidationAppError("Competitor name must contain letters or digits")
            if dup := await self._identity_taken(pid, normalized_name, exclude=competitor.id):
                raise ConflictError(f"'{name.strip()}' already identifies competitor {dup.name}")
            competitor.name = name.strip()
            competitor.normalized_name = normalized_name
        if website_url is not None:
            try:
                normalized_url = normalize_website_url(website_url)
            except InvalidURLError as exc:
                raise ValidationAppError(str(exc)) from exc
            nd = normalize_hostname(normalized_url.hostname) or normalized_url.hostname
            if nd != competitor.normalized_domain:
                if await self._is_own_domain(pid, nd):
                    raise ConflictError(f"{nd} is one of this project's own domains")
                if dup := await self._domain_taken(pid, nd, exclude=competitor.id):
                    raise ConflictError(f"Competitor {nd} is already tracked as {dup.name}")
                old_primary = next((d for d in competitor.domains if d.is_primary), None)
                if old_primary is not None:
                    old_primary.domain = nd
                else:
                    competitor.domains.append(
                        CompetitorDomain(domain=nd, domain_type="primary", is_primary=True)
                    )
            competitor.website_url = normalized_url.url
            competitor.hostname = normalized_url.hostname
            competitor.normalized_domain = nd
        if clear_description:
            competitor.description = None
        elif description is not None:
            competitor.description = description.strip() or None
        if status is not None:
            competitor.status = status.value
        if confidence is not None:
            competitor.confidence = confidence.value
        await self._session.flush()
        return await self.get_in_project(pid, competitor.id)

    async def delete(self, competitor: Competitor) -> None:
        await self._session.delete(competitor)
        await self._session.flush()

    # -- aliases -------------------------------------------------------------------------------

    async def add_alias(self, competitor: Competitor, alias: str) -> CompetitorAlias:
        alias = alias.strip()
        normalized = normalize_name(alias)
        if not normalized:
            raise ValidationAppError("Alias must contain letters or digits")
        if alias.lower() == competitor.name.lower():
            raise ConflictError("Alias is the competitor's own name")
        if any(a.alias.lower() == alias.lower() for a in competitor.aliases):
            raise ConflictError(f"Alias '{alias}' already exists")
        if dup := await self._identity_taken(
            competitor.project_id, normalized, exclude=competitor.id
        ):
            raise ConflictError(f"'{alias}' already identifies competitor {dup.name}")
        row = CompetitorAlias(competitor_id=competitor.id, alias=alias, normalized_alias=normalized)
        competitor.aliases.append(row)
        await self._session.flush()
        return row

    async def remove_alias(self, competitor: Competitor, alias_id: uuid.UUID) -> None:
        row = next((a for a in competitor.aliases if a.id == alias_id), None)
        if row is None:
            raise NotFoundError("Alias not found")
        competitor.aliases.remove(row)
        await self._session.flush()

    # -- domains -------------------------------------------------------------------------------

    async def add_domain(
        self,
        competitor: Competitor,
        domain: str,
        *,
        domain_type: CompetitorDomainType = CompetitorDomainType.OTHER,
        is_primary: bool = False,
    ) -> CompetitorDomain:
        normalized = normalize_hostname(domain)
        if normalized is None:
            raise ValidationAppError(f"'{domain}' is not a valid hostname")
        if any(d.domain == normalized for d in competitor.domains):
            raise ConflictError(f"Domain {normalized} already belongs to this competitor")
        if await self._is_own_domain(competitor.project_id, normalized):
            raise ConflictError(f"{normalized} is one of this project's own domains")
        if dup := await self._domain_taken(
            competitor.project_id, normalized, exclude=competitor.id
        ):
            raise ConflictError(f"Domain {normalized} already belongs to competitor {dup.name}")
        if is_primary:
            for d in competitor.domains:
                d.is_primary = False
        row = CompetitorDomain(
            competitor_id=competitor.id,
            domain=normalized,
            domain_type=domain_type.value,
            is_primary=is_primary,
        )
        competitor.domains.append(row)
        await self._session.flush()
        return row

    async def remove_domain(self, competitor: Competitor, domain_id: uuid.UUID) -> None:
        row = next((d for d in competitor.domains if d.id == domain_id), None)
        if row is None:
            raise NotFoundError("Domain not found")
        if row.is_primary:
            raise ConflictError(
                "The primary domain cannot be removed; change the website URL instead"
            )
        competitor.domains.remove(row)
        await self._session.flush()

    # -- products ------------------------------------------------------------------------------

    async def add_product(
        self,
        competitor: Competitor,
        *,
        name: str,
        description: str | None = None,
        url: str | None = None,
    ) -> CompetitorProduct:
        name = name.strip()
        normalized = normalize_name(name)
        if not normalized:
            raise ValidationAppError("Product name must contain letters or digits")
        if any(p.normalized_name == normalized for p in competitor.products):
            raise ConflictError(f"Product '{name}' already exists")
        if dup := await self._identity_taken(
            competitor.project_id, normalized, exclude=competitor.id
        ):
            raise ConflictError(f"'{name}' already identifies competitor {dup.name}")
        if url:
            try:
                url = normalize_website_url(url).url
            except InvalidURLError as exc:
                raise ValidationAppError(str(exc)) from exc
        row = CompetitorProduct(
            competitor_id=competitor.id,
            name=name,
            normalized_name=normalized,
            description=(description or "").strip() or None,
            url=url or None,
        )
        competitor.products.append(row)
        await self._session.flush()
        return row

    async def update_product(
        self,
        competitor: Competitor,
        product_id: uuid.UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        url: str | None = None,
    ) -> CompetitorProduct:
        row = next((p for p in competitor.products if p.id == product_id), None)
        if row is None:
            raise NotFoundError("Product not found")
        if name is not None and name.strip() != row.name:
            normalized = normalize_name(name)
            if not normalized:
                raise ValidationAppError("Product name must contain letters or digits")
            if any(p.normalized_name == normalized and p.id != row.id for p in competitor.products):
                raise ConflictError(f"Product '{name.strip()}' already exists")
            if dup := await self._identity_taken(
                competitor.project_id, normalized, exclude=competitor.id
            ):
                raise ConflictError(f"'{name.strip()}' already identifies competitor {dup.name}")
            row.name = name.strip()
            row.normalized_name = normalized
        if description is not None:
            row.description = description.strip() or None
        if url is not None:
            try:
                row.url = normalize_website_url(url).url if url.strip() else None
            except InvalidURLError as exc:
                raise ValidationAppError(str(exc)) from exc
        await self._session.flush()
        return row

    async def remove_product(self, competitor: Competitor, product_id: uuid.UUID) -> None:
        row = next((p for p in competitor.products if p.id == product_id), None)
        if row is None:
            raise NotFoundError("Product not found")
        competitor.products.remove(row)
        await self._session.flush()
