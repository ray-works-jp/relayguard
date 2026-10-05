"""Audit metadata chain (SCHEMA.md §9). Events carry IDs and hashes only, never raw content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .canonical import canonical_hash

ActorType = Literal["user", "system", "fixture"]


@dataclass(frozen=True)
class AuditEntry:
    actor_type: ActorType
    actor_id: str | None
    event_type: str
    entity_id: str
    entity_hash: str


def event_hash(event: dict[str, Any]) -> str:
    return canonical_hash({k: v for k, v in event.items() if k != "event_hash"})


def build_chain(
    case_id: str,
    entries: list[AuditEntry],
    event_ids: list[str],
    created_at: str,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    previous: str | None = None
    for entry, event_id in zip(entries, event_ids, strict=True):
        event: dict[str, Any] = {
            "event_id": event_id,
            "case_id": case_id,
            "actor_type": entry.actor_type,
            "actor_id": entry.actor_id,
            "event_type": entry.event_type,
            "entity_id": entry.entity_id,
            "entity_hash": entry.entity_hash,
            "previous_hash": previous,
            "created_at": created_at,
        }
        event["event_hash"] = event_hash(event)
        previous = event["event_hash"]
        events.append(event)
    return events


def verify_chain(case_id: str, events: list[dict[str, Any]]) -> bool:
    previous: str | None = None
    seen: set[str] = set()
    for event in events:
        if event["case_id"] != case_id or event["event_id"] in seen:
            return False
        if event["previous_hash"] != previous or event["event_hash"] != event_hash(event):
            return False
        seen.add(event["event_id"])
        previous = event["event_hash"]
    return bool(events)
