"""PSA grading lookups via the official PSA Public API.

PSA's free API only supports single-cert lookups
(``cert/GetByCertNumber/{cert}``) and returns grade + population data for that
certificate. It does **not** expose card prices, and population fields are
sometimes ``null``. A bearer token (from psacard.com/publicapi) is required.

Every call is fail-soft: on missing token / network / parse errors it returns
``None`` so the surrounding sync keeps working.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app import settings_store
from app.config import settings

logger = logging.getLogger(__name__)

_PSA_CERT_API = "https://api.psacard.com/publicapi/cert/GetByCertNumber"


@dataclass(frozen=True)
class PsaCert:
    cert_number: str
    grade: str | None
    subject: str | None
    year: str | None
    brand: str | None
    card_number: str | None
    variety: str | None
    spec_id: str | None
    population_total: int | None
    population_higher: int | None
    raw_json: str


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_cert(cert_number: str, body: Any) -> PsaCert | None:
    # The public API returns ``{"PSACert": {...}}`` for a valid cert. Older docs
    # mention an ``IsValidRequest`` flag, but live responses omit it, so we only
    # require the ``PSACert`` object itself.
    if not isinstance(body, dict):
        return None
    if body.get("IsValidRequest") is False:
        return None
    cert = body.get("PSACert")
    if not isinstance(cert, dict):
        return None
    return PsaCert(
        cert_number=cert_number,
        grade=_clean_str(cert.get("CardGrade") or cert.get("GradeDescription")),
        subject=_clean_str(cert.get("Subject")),
        year=_clean_str(cert.get("Year")),
        brand=_clean_str(cert.get("Brand")),
        card_number=_clean_str(cert.get("CardNumber")),
        variety=_clean_str(cert.get("Variety")),
        spec_id=_clean_str(cert.get("SpecID")),
        population_total=_as_int(cert.get("TotalPopulation")),
        population_higher=_as_int(cert.get("PopulationHigher")),
        raw_json=json.dumps(body, ensure_ascii=True),
    )


async def fetch_cert(cert_number: str) -> PsaCert | None:
    cert_number = (cert_number or "").strip()
    token = settings_store.get_str("psa_api_token").strip()
    if not cert_number or not token:
        return None

    url = f"{_PSA_CERT_API}/{cert_number}"
    headers = {"Authorization": f"bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url, headers=headers)
        if response.status_code != 200:
            return None
        body = response.json()
    except Exception:  # noqa: BLE001 - never let a PSA lookup break sync
        logger.warning("PSA cert lookup failed for %s", cert_number, exc_info=True)
        return None

    return parse_cert(cert_number, body)
