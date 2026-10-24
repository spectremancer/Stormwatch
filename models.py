"""Shared contracts for provider data and application state."""
from enum import StrEnum
from typing import TypedDict


class HealthStatus(StrEnum):
    PAUSED = 'PAUSED'
    CONNECTING = 'CONNECTING'
    NO_LIVE_DATA = 'NO LIVE DATA'
    LIVE = 'LIVE'
    DEGRADED = 'DEGRADED'
    STALE = 'STALE'


class AlertData(TypedDict, total=False):
    id: str
    event: str
    headline: str
    area: str
    sent: str
    ends: str
    expires: str
    severity: str
    urgency: str
    instruction: str
    description: str
    message_type: str
    references: list
    geocode: dict
    geometry: dict | None
    zones: list[str]
    simulated: bool


NotificationJob = tuple[AlertData,str,str,str,str]
