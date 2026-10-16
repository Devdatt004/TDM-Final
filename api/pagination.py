"""Bounded pagination shared by list endpoints (Step 15)."""
from dataclasses import dataclass

from fastapi import Query

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


@dataclass(frozen=True)
class Page:
    limit: int
    offset: int


def page_params(
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT, description=f"Page size (max {MAX_LIMIT})."),
    offset: int = Query(default=0, ge=0, description="Rows to skip."),
) -> Page:
    return Page(limit=limit, offset=offset)


def paginate(query, page: Page):
    """(total, items) for an ordered SQLAlchemy query."""
    return query.count(), query.offset(page.offset).limit(page.limit).all()


def envelope(page: Page, total: int) -> dict:
    return {"total": total, "limit": page.limit, "offset": page.offset}
