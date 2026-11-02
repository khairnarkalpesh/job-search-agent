"""Calls the real public APIs. Run with: pytest -m live

Boards are chosen at run time from the ones the last search saved, so these
tests do not depend on any particular company.
"""
import pytest

from conftest import REAL_USER_HOME
from http_client import FetchError, HttpClient
from job_storage import JobStore
from sources import SOURCES, JobBoard

pytestmark = pytest.mark.live


def saved_board(source):
    boards = [board for folder in ("data", "synthetic_run_output")
              for board in JobStore(REAL_USER_HOME / folder).known_boards() if board.source == source]
    if not boards:
        pytest.skip(f"No saved {source} board yet")
    return boards[0]


@pytest.mark.parametrize("source", ["greenhouse", "lever"])
def test_live_board_returns_listings_with_full_descriptions(source):
    jobs = SOURCES[source].fetch_board(saved_board(source), HttpClient())
    assert jobs
    assert all(job["title"] and job["source_url"].startswith("https://") for job in jobs)
    assert sum(len(job["description"]) > 300 for job in jobs) > len(jobs) / 2


@pytest.mark.parametrize("source", ["greenhouse", "lever"])
def test_live_unknown_board_is_reported_as_not_found(source):
    with pytest.raises(FetchError) as error:
        SOURCES[source].fetch_board(JobBoard(source, "no-such-company-board-xyz"), HttpClient())
    assert error.value.kind == "not_found"
