from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_DEVICE_CACHE_KEY = getattr(settings, "DEVICE_CACHE_REDIS_HASH", "realtime:devices")
_DEVICE_CACHE_URL = getattr(settings, "DEVICE_CACHE_REDIS_URL", None)

_local_cache: Dict[str, Dict[str, Any]] = {}
_redis_client = None
_setup_attempted = False


def _determine_redis_url() -> Optional[str]:
    if _DEVICE_CACHE_URL:
        return _DEVICE_CACHE_URL
    return getattr(settings, "REDIS_URL", None) or None


def _get_redis_client():
    global _redis_client, _setup_attempted
    if _redis_client is not None:
        return _redis_client
    if _setup_attempted:
        return None
    _setup_attempted = True

    url = _determine_redis_url()
    if not url:
        return None

    try:
        import redis  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency missing
        logger.warning(
            "redis-py not available; falling back to in-memory cache (%s)", exc
        )
        return None

    try:
        client = redis.Redis.from_url(url)
        client.ping()
        _redis_client = client
        logger.info("Device cache configured to use Redis at %s", url)
        return _redis_client
    except Exception as exc:
        logger.warning(
            "Unable to reach Redis device cache at %s; using in-memory fallback (%s)",
            url,
            exc,
        )
        _redis_client = None
        return None


def _clone(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure the payload stored in-memory is isolated from callers
    return json.loads(json.dumps(payload))


def set_device_state(device_id: str, payload: Dict[str, Any]) -> None:
    """Persist latest device payload for WebSocket snapshots."""

    _local_cache[device_id] = _clone(payload)

    client = _get_redis_client()
    if not client:
        return

    try:
        client.hset(_DEVICE_CACHE_KEY, device_id, json.dumps(payload))
    except Exception as exc:
        logger.warning(
            "Failed to write device %s to Redis cache; continuing with local cache (%s)",
            device_id,
            exc,
        )


def remove_device(device_id: str) -> None:
    """Remove device payload from caches."""

    _local_cache.pop(device_id, None)

    client = _get_redis_client()
    if not client:
        return

    try:
        client.hdel(_DEVICE_CACHE_KEY, device_id)
    except Exception as exc:
        logger.warning(
            "Failed to delete device %s from Redis cache: %s", device_id, exc
        )


def replace_all(states: Dict[str, Dict[str, Any]]) -> None:
    """Replace the entire cache with the provided mapping."""

    global _local_cache
    _local_cache = {k: _clone(v) for k, v in states.items()}

    client = _get_redis_client()
    if not client:
        return

    try:
        if states:
            mapping = {k: json.dumps(v) for k, v in states.items()}
            with client.pipeline() as pipe:
                pipe.delete(_DEVICE_CACHE_KEY)
                pipe.hset(_DEVICE_CACHE_KEY, mapping=mapping)
                pipe.execute()
        else:
            client.delete(_DEVICE_CACHE_KEY)
    except Exception as exc:
        logger.warning(
            "Failed to replace Redis device cache; using local copy (%s)", exc
        )


def get_all_states() -> List[Dict[str, Any]]:
    """Return all known device payloads."""

    client = _get_redis_client()
    if client:
        try:
            raw = client.hgetall(_DEVICE_CACHE_KEY)
            if raw:
                result: List[Dict[str, Any]] = []
                for value in raw.values():
                    try:
                        if isinstance(value, (bytes, bytearray)):
                            result.append(json.loads(value.decode("utf-8")))
                        else:
                            result.append(json.loads(value))
                    except Exception:
                        continue
                if result:
                    return result
        except Exception as exc:
            logger.warning(
                "Error reading Redis device cache; falling back to local copy (%s)", exc
            )

    return [_clone(payload) for payload in _local_cache.values()]


def get_state(device_id: str) -> Optional[Dict[str, Any]]:
    client = _get_redis_client()
    if client:
        try:
            value = client.hget(_DEVICE_CACHE_KEY, device_id)
            if value:
                if isinstance(value, (bytes, bytearray)):
                    return json.loads(value.decode("utf-8"))
                return json.loads(value)
        except Exception as exc:
            logger.warning(
                "Error reading device %s from Redis cache; falling back (%s)",
                device_id,
                exc,
            )
    payload = _local_cache.get(device_id)
    return _clone(payload) if payload else None
