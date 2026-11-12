"""Immutable raw storage (bronze layer). See docs/adr/0002."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RawItem:
    """One item as returned by a source, plus the source's own timestamp."""

    source_id: str
    payload: dict[str, Any]
    event_time: datetime | None = None


@dataclass(frozen=True)
class WriteResult:
    source: str
    run_id: str
    path: Path | None
    records: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_run_id(now: datetime) -> str:
    return f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(f"naive datetime is ambiguous: {value!r}")
    return value.astimezone(UTC).isoformat()


class BronzeWriter:
    def __init__(self, root: Path, clock: Callable[[], datetime] = utc_now) -> None:
        self.root = Path(root)
        self.clock = clock

    def write(self, source: str, items: Iterable[RawItem], run_id: str | None = None) -> WriteResult:
        """Stream items to a new partition file; nothing is written if there are no items."""
        started = self.clock()
        run_id = run_id or new_run_id(started)
        path = self.root / f"source={source}" / f"ingest_date={started:%Y-%m-%d}" / f"run={run_id}.jsonl"
        if path.exists():
            raise FileExistsError(f"bronze files are immutable: {path}")

        tmp = path.with_suffix(".jsonl.tmp")
        handle = None
        count = 0
        try:
            for item in items:
                line = canonical_json(self._record(source, run_id, item)) + "\n"
                if handle is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = tmp.open("w", encoding="utf-8")
                handle.write(line)
                count += 1
        except BaseException:
            if handle is not None:
                handle.close()
                tmp.unlink(missing_ok=True)
            raise

        if handle is None:
            return WriteResult(source, run_id, None, 0)

        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(tmp, path)
        return WriteResult(source, run_id, path, count)

    def _record(self, source: str, run_id: str, item: RawItem) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "source": source,
            "source_id": item.source_id,
            "run_id": run_id,
            "fetched_at": _iso(self.clock()),
            "event_time": _iso(item.event_time),
            "payload_sha256": payload_hash(item.payload),
            "payload": item.payload,
        }


def read_records(root: Path, source: str) -> Iterator[dict[str, Any]]:
    """Yield every bronze record of a source, oldest partition first."""
    for path in sorted((Path(root) / f"source={source}").glob("ingest_date=*/run=*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
