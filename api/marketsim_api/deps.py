"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .jobs import JobRegistry
from .storage import Store


def get_store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


StoreDep = Annotated[Store, Depends(get_store)]


def get_jobs(request: Request) -> JobRegistry | None:
    jobs: JobRegistry | None = request.app.state.jobs
    return jobs


JobsDep = Annotated[JobRegistry | None, Depends(get_jobs)]
