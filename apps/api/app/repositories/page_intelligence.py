import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.intelligence import PageIntelligence, observations_as_dict
from app.models.crawl import WebsitePage
from app.models.page_intelligence import (
    LinkStatus,
    LinkType,
    PageContentMetrics,
    PageHeading,
    PageImage,
    PageLink,
    PageMetadata,
    PageStructuredData,
    StructuredDataFormat,
)


class PageIntelligenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_page(
        self,
        page: WebsitePage,
        version_id: uuid.UUID | None,
        intel: PageIntelligence,
    ) -> None:
        """Replace every intelligence row for `page` with the new analysis."""
        for model in (
            PageHeading,
            PageLink,
            PageImage,
            PageMetadata,
            PageContentMetrics,
            PageStructuredData,
        ):
            await self._session.execute(delete(model).where(model.page_id == page.id))

        common = {"page_id": page.id, "project_id": page.project_id, "page_version_id": version_id}
        self._session.add_all(
            PageHeading(
                level=h.level,
                position=h.position,
                parent_position=h.parent_position,
                text=h.text,
                **common,
            )
            for h in intel.headings
        )
        self._session.add_all(
            PageLink(
                href=link.href,
                normalized_url=link.normalized_url,
                anchor_text=link.anchor_text,
                link_type=LinkType(link.link_type),
                status=LinkStatus.INVALID if link.normalized_url is None else LinkStatus.UNKNOWN,
                is_nofollow=link.is_nofollow,
                is_sponsored=link.is_sponsored,
                is_ugc=link.is_ugc,
                in_navigation=link.in_navigation,
                position=link.position,
                **common,
            )
            for link in intel.links
        )
        self._session.add_all(
            PageImage(
                src=i.src,
                alt=i.alt,
                title=i.title,
                width=i.width,
                height=i.height,
                loading=i.loading,
                position=i.position,
                **common,
            )
            for i in intel.images
        )
        m = intel.metadata
        self._session.add(
            PageMetadata(
                pathname=intel.pathname,
                robots=m.robots,
                viewport=m.viewport,
                author=m.author,
                charset=m.charset,
                published_at=m.published_at,
                modified_at=m.modified_at,
                html_lang=m.html_lang[:35] if m.html_lang else None,
                language=intel.language.code,
                language_source=intel.language.source,
                language_confidence=intel.language.confidence,
                open_graph=m.open_graph,
                twitter=m.twitter,
                other=m.extra,
                has_doctype=intel.validity.has_doctype,
                title_count=intel.validity.title_count,
                canonical_count=intel.validity.canonical_count,
                canonical_url=intel.validity.canonical_url,
                **common,
            )
        )
        self._session.add_all(
            PageStructuredData(
                format=StructuredDataFormat(sd.format),
                schema_types=sd.schema_types,
                payload=sd.payload,
                is_valid=sd.is_valid,
                error=sd.error,
                position=sd.position,
                **common,
            )
            for sd in intel.structured_data
        )
        c = intel.content
        self._session.add(
            PageContentMetrics(
                word_count=c.word_count,
                character_count=c.character_count,
                paragraph_count=c.paragraph_count,
                sentence_count=c.sentence_count,
                reading_time_seconds=c.reading_time_seconds,
                text_to_html_ratio=c.text_to_html_ratio,
                html_bytes=c.html_bytes,
                heading_count=len(intel.headings),
                h1_count=intel.heading_observations.h1_count,
                link_count=len(intel.links),
                internal_link_count=sum(1 for x in intel.links if x.link_type == "internal"),
                external_link_count=sum(
                    1
                    for x in intel.links
                    if x.link_type == "external" and x.normalized_url is not None
                ),
                image_count=len(intel.images),
                images_missing_alt=sum(1 for i in intel.images if not i.alt),
                heading_observations=observations_as_dict(intel.heading_observations),
                clean_text=intel.clean_text,
                **common,
            )
        )
        await self._session.flush()

    async def resolve_internal_links(self, project_id: uuid.UUID) -> int:
        """Point internal links at crawled pages and mark 4xx/5xx targets broken.

        Runs at the end of a crawl so targets discovered later are still resolved.
        Returns the number of links updated.
        """
        base = update(PageLink).where(
            PageLink.project_id == project_id,
            PageLink.link_type == LinkType.INTERNAL,
            PageLink.normalized_url == WebsitePage.normalized_url,
            WebsitePage.project_id == project_id,
        )
        ok = await self._session.execute(
            base.where(WebsitePage.http_status < 400).values(
                target_page_id=WebsitePage.id,
                target_http_status=WebsitePage.http_status,
                status=LinkStatus.OK,
            )
        )
        broken = await self._session.execute(
            base.where(WebsitePage.http_status >= 400).values(
                target_page_id=WebsitePage.id,
                target_http_status=WebsitePage.http_status,
                status=LinkStatus.BROKEN,
            )
        )
        ok_n = getattr(ok, "rowcount", 0) or 0
        broken_n = getattr(broken, "rowcount", 0) or 0
        return int(ok_n) + int(broken_n)

    async def headings_for_page(self, page_id: uuid.UUID) -> list[PageHeading]:
        stmt = (
            select(PageHeading).where(PageHeading.page_id == page_id).order_by(PageHeading.position)
        )
        return list((await self._session.scalars(stmt)).all())

    async def links_for_page(
        self,
        page_id: uuid.UUID,
        *,
        link_type: LinkType | None = None,
        status: LinkStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[PageLink], int]:
        base = select(PageLink).where(PageLink.page_id == page_id)
        if link_type is not None:
            base = base.where(PageLink.link_type == link_type)
        if status is not None:
            base = base.where(PageLink.status == status)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self._session.scalars(
            base.order_by(PageLink.position).limit(limit).offset(offset)
        )
        return list(rows.all()), int(total or 0)

    async def structured_data_for_page(self, page_id: uuid.UUID) -> list[PageStructuredData]:
        stmt = (
            select(PageStructuredData)
            .where(PageStructuredData.page_id == page_id)
            .order_by(PageStructuredData.position)
        )
        return list((await self._session.scalars(stmt)).all())

    async def images_for_page(self, page_id: uuid.UUID) -> list[PageImage]:
        stmt = select(PageImage).where(PageImage.page_id == page_id).order_by(PageImage.position)
        return list((await self._session.scalars(stmt)).all())

    async def metadata_for_page(self, page_id: uuid.UUID) -> PageMetadata | None:
        stmt = select(PageMetadata).where(PageMetadata.page_id == page_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def metrics_for_page(self, page_id: uuid.UUID) -> PageContentMetrics | None:
        stmt = select(PageContentMetrics).where(PageContentMetrics.page_id == page_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def metrics_for_pages(
        self, page_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, PageContentMetrics]:
        if not page_ids:
            return {}
        rows = await self._session.scalars(
            select(PageContentMetrics).where(PageContentMetrics.page_id.in_(list(page_ids)))
        )
        return {r.page_id: r for r in rows.all()}
