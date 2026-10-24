"""Application-scoped dependencies; the scheduler and API share one worker pool."""

from fastapi import Request

from app.core.database import Database
from app.core.downloader import Downloader


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_downloader(request: Request) -> Downloader:
    return request.app.state.downloader
