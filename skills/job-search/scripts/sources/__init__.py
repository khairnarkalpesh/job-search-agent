"""Source adapters. To add a job source, write a module with a Source subclass and list it here."""
from __future__ import annotations

from .ashby import AshbySource
from .base import JobBoard, Source
from .generic import GenericSource
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .portals import ArbeitnowSource, HimalayasSource, RemoteOkSource, RemotiveSource
from .smartrecruiters import SmartRecruitersSource
from .workable import WorkableSource

SOURCES: dict[str, Source] = {source.name: source for source in (
    GreenhouseSource(), LeverSource(), AshbySource(), WorkableSource(), SmartRecruitersSource(),
    RemotiveSource(), RemoteOkSource(), HimalayasSource(), ArbeitnowSource(), GenericSource())}
ATS_SOURCES = [name for name, source in SOURCES.items() if source.kind == "ats"]
PORTAL_SOURCES = [name for name, source in SOURCES.items() if source.kind == "portal"]


def board_from_url(url: str) -> JobBoard | None:
    """Find which source a URL belongs to. The generic website reader is the fallback."""
    for source_name in ATS_SOURCES + ["generic"]:
        board = SOURCES[source_name].parse_url(url)
        if board:
            return board
    return None


__all__ = ["ATS_SOURCES", "JobBoard", "PORTAL_SOURCES", "SOURCES", "Source", "board_from_url"]
