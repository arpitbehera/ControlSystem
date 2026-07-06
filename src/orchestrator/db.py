"""Engine factory + active-pointer queries."""

from __future__ import annotations

import sqlalchemy as sa


def make_engine(url: str) -> sa.Engine:
    return sa.create_engine(url, pool_pre_ping=True)


_ACTIVE_DESCRIPTOR = sa.text(
    "SELECT descriptor_id FROM descriptor_activations"
    " WHERE lineage = :lineage ORDER BY activated_at DESC, id DESC LIMIT 1"
)
_ACTIVE_SNAPSHOT = sa.text(
    "SELECT snapshot_id FROM snapshot_activations"
    " WHERE lineage = :lineage ORDER BY activated_at DESC, id DESC LIMIT 1"
)


def active_descriptor_id(conn: sa.Connection, lineage: str = "default") -> int | None:
    return conn.execute(_ACTIVE_DESCRIPTOR, {"lineage": lineage}).scalar()


def active_snapshot_id(conn: sa.Connection, lineage: str = "default") -> int | None:
    return conn.execute(_ACTIVE_SNAPSHOT, {"lineage": lineage}).scalar()
