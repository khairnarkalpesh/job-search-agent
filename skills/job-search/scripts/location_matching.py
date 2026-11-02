"""Decide whether a job's location works for the candidate."""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from skill_taxonomy import taxonomy

_REMOTE_RESTRICTION = re.compile(
    r"(?:must|need to|needs to|required to|should)\s+(?:be\s+)?(?:reside|live|located|based)\s+in\s+(?:the\s+)?([^.;\n]{2,50})",
    re.IGNORECASE)
_REMOTE_WORD = re.compile(r"\bremote\b", re.IGNORECASE)


def _alias_pattern(alias: str) -> re.Pattern:
    # Short forms such as US, UK, SF and ", CA" are only meaningful in capitals.
    case_sensitive = len(alias) <= 3 or alias.startswith(",")
    if alias.startswith(","):
        return re.compile(re.escape(alias) + r"\b")
    return re.compile(rf"(?<![\w.]){re.escape(alias)}(?![\w])", 0 if case_sensitive else re.IGNORECASE)


@functools.lru_cache(maxsize=1)
def _country_patterns() -> list[tuple[str, re.Pattern]]:
    return [(country, re.compile("|".join(_alias_pattern(alias).pattern for alias in aliases if len(alias) <= 3 or alias.startswith(",")) or r"(?!)"))
            for country, aliases in taxonomy()["locations"]["countries"].items()]


@functools.lru_cache(maxsize=1)
def _long_country_patterns() -> list[tuple[str, re.Pattern]]:
    return [(country, re.compile("|".join(_alias_pattern(alias).pattern for alias in aliases if len(alias) > 3 and not alias.startswith(",")) or r"(?!)", re.IGNORECASE))
            for country, aliases in taxonomy()["locations"]["countries"].items()]


def countries_in(text: str) -> set[str]:
    """Countries named or implied by a location string, including regions such as EMEA."""
    found = {country for country, pattern in _country_patterns() if pattern.search(text)}
    found |= {country for country, pattern in _long_country_patterns() if pattern.search(text)}
    for region, members in taxonomy()["locations"]["regions"].items():
        flags = 0 if len(region) <= 2 else re.IGNORECASE
        name = region.upper() if len(region) <= 2 else region
        if re.search(rf"\b{re.escape(name)}\b", text, flags):
            found |= set(members)
    return found


def is_global_location(text: str) -> bool:
    terms = taxonomy()["locations"]["global_terms"]
    return any(re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE) for term in terms)


@dataclass(frozen=True)
class LocationMatch:
    status: str  # match, partial, mismatch or unknown
    reason: str


def candidate_targets(profile: dict, preferences: dict, location_filter: str = "") -> list[str]:
    """Where the candidate wants to work: this run's filter, saved preferences, then the resume."""
    if location_filter:
        targets = [part.strip() for part in location_filter.split(",") if part.strip()]
    else:
        targets = list(preferences.get("target_locations") or profile.get("preferred_locations") or [])
    home = profile["candidate"].get("location", "")
    if home and (not targets or all(target.lower() == "remote" for target in targets)):
        targets.append(home)
    return targets


def match_location(job: dict, targets: list[str]) -> LocationMatch:
    location = job.get("location", "")
    if not targets:
        return LocationMatch("unknown", "No location in resume or preferences to compare with")
    if not location:
        return LocationMatch("unknown", "Listing does not state a location")

    named_targets = [target for target in targets if target.lower() != "remote"]
    target_countries = set().union(*(countries_in(target) for target in named_targets)) if named_targets else set()
    job_countries = countries_in(location)
    is_remote = job.get("remote") is True or bool(_REMOTE_WORD.search(location))

    for target in named_targets:
        city = target.split(",")[0].strip()
        if city and re.search(rf"\b{re.escape(city)}\b", location, re.IGNORECASE) \
                and not (is_remote and countries_in(target) - job_countries):
            return LocationMatch("match", f"Listing location {location} includes {city}")

    if is_remote:
        restriction = _REMOTE_RESTRICTION.search(job.get("description", ""))
        restricted_to = countries_in(restriction.group(1)) if restriction else set()
        allowed = (job_countries & restricted_to or job_countries or restricted_to) if not is_global_location(location) else restricted_to
        if not allowed:
            return LocationMatch("match", f"Remote with no stated country limit ({location})")
        if not target_countries or allowed & target_countries:
            return LocationMatch("match", f"Remote and open to your location ({location})")
        return LocationMatch("mismatch", f"Remote, but limited to {location if job_countries else restriction.group(1).strip()}")

    if not job_countries:
        return LocationMatch("unknown", f"Could not place listing location: {location}")
    if not target_countries:
        return LocationMatch("mismatch", f"On-site in {location}, and you asked for remote")
    if job_countries & target_countries:
        return LocationMatch("partial", f"Same country, different city: {location}")
    return LocationMatch("mismatch", f"On-site or hybrid in {location}, outside your target locations")
