"""``data_versions`` rows for importer results.

Only called with a Session the caller owns; nothing here opens a connection by itself.
A source has at most one ``active`` row: activating a version demotes the previous one to
``staged`` (decision 36).
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.common.models import DataVersion
from backend.importers.result import ImportResult

_ROW_STATUS = {"staged": "staged", "rejected": "rejected"}


def record_result(session: Session, result: ImportResult) -> DataVersion | None:
    """Store a staged or rejected result; unchanged and failed results write nothing."""
    status = _ROW_STATUS.get(result.status)
    if status is None or result.version is None:
        return None
    row = session.get(DataVersion, (result.source, result.version))
    if row is not None and row.status == "active":
        return row  # re-staging or rejecting never demotes the active version
    if row is None:
        row = DataVersion(source=result.source, version=result.version)
        session.add(row)
    row.status = status
    row.fetched_at = datetime.now(UTC)
    row.files = result.files
    session.flush()
    return row


def activate(session: Session, source: str, version: str) -> DataVersion:
    """Make ``version`` the single active row of ``source`` (decision 36).

    The previous active row goes back to ``staged``, so rolling back is ``activate`` on it.
    """
    row = session.get(DataVersion, (source, version))
    if row is None or row.status not in ("staged", "active"):
        raise ValueError(f"{source} {version} is not a staged or active version")
    for other in session.scalars(
        select(DataVersion).where(
            DataVersion.source == source,
            DataVersion.status == "active",
            DataVersion.version != version,
        )
    ):
        other.status = "staged"
    row.status = "active"
    session.flush()
    return row


def active_version(session: Session, source: str) -> str | None:
    return session.scalars(
        select(DataVersion.version)
        .where(DataVersion.source == source, DataVersion.status == "active")
        .order_by(DataVersion.fetched_at.desc())
        .limit(1)
    ).first()
