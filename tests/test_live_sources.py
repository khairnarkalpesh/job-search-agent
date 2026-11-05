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


MAX_BOARDS_TRIED = 5


def saved_boards(source):
    boards = [board for folder in ("data", "synthetic_run_output")
              for board in JobStore(REAL_USER_HOME / folder).known_boards() if board.source == source]
    if not boards:
        pytest.skip(f"No saved {source} board yet")
    return boards[:MAX_BOARDS_TRIED]


@pytest.mark.parametrize("source", ["greenhouse", "lever"])
def test_live_board_returns_listings_with_full_descriptions(source):
    # A company can have no openings today; the first saved board with listings is checked.
    client = HttpClient()
    jobs = next((found for board in saved_boards(source) if (found := SOURCES[source].fetch_board(board, client))), [])
    if not jobs:
        pytest.skip(f"None of the first {MAX_BOARDS_TRIED} saved {source} boards has open listings today")
    assert all(job["title"] and job["source_url"].startswith("https://") for job in jobs)
    assert sum(len(job["description"]) > 300 for job in jobs) > len(jobs) / 2


@pytest.mark.parametrize("source", ["greenhouse", "lever"])
def test_live_unknown_board_is_reported_as_not_found(source):
    with pytest.raises(FetchError) as error:
        SOURCES[source].fetch_board(JobBoard(source, "no-such-company-board-xyz"), HttpClient())
    assert error.value.kind == "not_found"
