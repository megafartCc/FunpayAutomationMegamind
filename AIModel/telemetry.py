from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend import config as app_config
from backend.logger import logger


def _now_ts() -> float:
    return time.time()


def _hash_owner(owner: str) -> str:
    return hashlib.sha1(owner.encode("utf-8")).hexdigest()


@dataclass
class TelemetryState:
    counters: Dict[str, int] = field(default_factory=dict)
    actions: Dict[str, int] = field(default_factory=dict)
    errors: Dict[str, int] = field(default_factory=dict)
    latencies_ms: List[float] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


class TelemetryStore:
    def __init__(self, path: str, max_events: int = 200) -> None:
        self._path = Path(path)
        self._max_events = max(1, int(max_events))
        self._lock = threading.Lock()
        self._state = TelemetryState()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        self._state = TelemetryState(
            counters=dict(data.get("counters") or {}),
            actions=dict(data.get("actions") or {}),
            errors=dict(data.get("errors") or {}),
            latencies_ms=list(data.get("latencies_ms") or []),
            events=list(data.get("events") or []),
        )
        if len(self._state.events) > self._max_events:
            self._state.events = self._state.events[-self._max_events:]

    def _save(self) -> None:
        payload = {
            "counters": self._state.counters,
            "actions": self._state.actions,
            "errors": self._state.errors,
            "latencies_ms": self._state.latencies_ms[-self._max_events :],
            "events": self._state.events[-self._max_events :],
            "updated_at": _now_ts(),
        }
        tmp_path = self._path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False)
            tmp_path.replace(self._path)
        except Exception as exc:
            logger.warning("Failed to save AI metrics: %s", exc)

    def _inc(self, target: Dict[str, int], key: str, amount: int = 1) -> None:
        target[key] = int(target.get(key) or 0) + int(amount)

    def record_request(self, owner: str | None = None) -> None:
        with self._lock:
            self._inc(self._state.counters, "requests_total")
            if owner:
                self._inc(self._state.counters, f"requests_owner_{_hash_owner(owner)}")
            self._save()

    def record_error(self, kind: str) -> None:
        with self._lock:
            self._inc(self._state.errors, kind)
            self._inc(self._state.counters, "errors_total")
            self._save()

    def record_action(
        self,
        owner: str | None,
        action: str,
        latency_ms: float | None,
        status: str,
        reason: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        variant: str | None = None,
    ) -> None:
        event = {
            "ts": _now_ts(),
            "action": action,
            "status": status,
        }
        if owner:
            event["owner_hash"] = _hash_owner(owner)
        if latency_ms is not None:
            event["latency_ms"] = float(latency_ms)
        if reason:
            event["reason"] = reason
        if provider:
            event["provider"] = provider
        if model:
            event["model"] = model
        if variant:
            event["variant"] = variant

        with self._lock:
            self._inc(self._state.actions, action)
            self._inc(self._state.counters, "responses_total")
            if status != "ok":
                self._inc(self._state.errors, status)
            if latency_ms is not None:
                self._state.latencies_ms.append(float(latency_ms))
                if len(self._state.latencies_ms) > self._max_events:
                    self._state.latencies_ms = self._state.latencies_ms[-self._max_events:]
            self._state.events.append(event)
            if len(self._state.events) > self._max_events:
                self._state.events = self._state.events[-self._max_events:]
            self._save()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            latencies = list(self._state.latencies_ms)
            latencies.sort()
            p50 = _percentile(latencies, 0.5)
            p95 = _percentile(latencies, 0.95)
            total = int(self._state.counters.get("requests_total") or 0)
            errors = int(self._state.counters.get("errors_total") or 0)
            error_rate = (errors / total) if total else 0.0
            error_budget_target = float(app_config.AI_ERROR_BUDGET_TARGET or 0.0)
            error_budget_remaining = max(0.0, error_budget_target - error_rate)
            return {
                "counters": dict(self._state.counters),
                "actions": dict(self._state.actions),
                "errors": dict(self._state.errors),
                "latency_ms": {
                    "p50": p50,
                    "p95": p95,
                    "samples": len(latencies),
                },
                "error_rate": error_rate,
                "error_budget": {
                    "target": error_budget_target,
                    "remaining": error_budget_remaining,
                },
                "events": list(self._state.events),
            }


def _percentile(values: List[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    idx = int(round((len(values) - 1) * quantile))
    idx = max(0, min(idx, len(values) - 1))
    return float(values[idx])


_telemetry: Optional[TelemetryStore] = None


def get_telemetry() -> TelemetryStore:
    global _telemetry
    if _telemetry is None:
        _telemetry = TelemetryStore(
            path=app_config.AI_METRICS_PATH,
            max_events=app_config.AI_METRICS_MAX_EVENTS,
        )
    return _telemetry


__all__ = ["TelemetryStore", "get_telemetry"]
