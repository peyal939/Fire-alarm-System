from __future__ import annotations

import os
import inspect
from dataclasses import dataclass
import logging
import json
from types import SimpleNamespace
from urllib import request as urlrequest, parse as urlparse, error as urlerror
from typing import Optional

from django.conf import settings

# Import plugin package (installed via requirements)
from shurjopay_plugin import (
    ShurjopayPlugin,
    ShurjoPayConfigModel,
    PaymentRequestModel,
    ShurjopayException,
    ShurjopayAuthException,
)


logger = logging.getLogger(__name__)


@dataclass
class ShurjoEnv:
    username: str
    password: str
    endpoint: str
    ret_url: str
    cancel_url: str
    prefix: str
    logdir: str | None
    verify_mode: str  # 'auto' (default), 'raw', or 'plugin'


def _prepare_log_path(path: str | None) -> str:
    if not path:
        return ""
    log = logging.getLogger(__name__)
    try:
        normalized = os.path.abspath(os.path.expanduser(str(path)))
        directory = os.path.dirname(normalized)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        return normalized
    except Exception as exc:  # pragma: no cover - best effort fallback
        log.warning("Unable to prepare shurjoPay log path %s: %s", path, exc)
        return ""


def load_env() -> ShurjoEnv:
    return ShurjoEnv(
        username=os.getenv("SP_USERNAME", ""),
        password=os.getenv("SP_PASSWORD", ""),
        endpoint=os.getenv("SP_ENDPOINT", ""),
        ret_url=os.getenv("SP_RETURN", ""),
        cancel_url=os.getenv("SP_CANCEL", ""),
        prefix=os.getenv("SP_PREFIX", "SP_PLUGIN_PYTHON"),
        logdir=os.getenv("SP_LOGDIR") or None,
        verify_mode=(os.getenv("SP_VERIFY_MODE", "auto") or "auto").lower(),
    )


def build_plugin() -> ShurjopayPlugin:
    env = load_env()
    log_path = _prepare_log_path(env.logdir)
    cfg = ShurjoPayConfigModel(
        SP_USERNAME=env.username,
        SP_PASSWORD=env.password,
        SP_ENDPOINT=env.endpoint,
        SP_RETURN=env.ret_url,
        SP_CANCEL=env.cancel_url,
        SP_PREFIX=env.prefix,
        SP_LOGDIR=log_path,
    )
    return ShurjopayPlugin(cfg)


def initiate_payment(
    *,
    amount: float,
    order_id: str,
    currency: str = "BDT",
    customer_name: str = "",
    customer_address: str = "",
    customer_phone: str = "",
    customer_city: str = "",
    customer_post_code: str = "",
    customer_email: str = "",
    client_ip: str = "",
):
    plugin = build_plugin()
    # Build payload and filter to only accepted fields of PaymentRequestModel
    payload = {
        "amount": amount,
        "order_id": order_id,
        "currency": currency,
        "customer_name": customer_name,
        "customer_address": customer_address,
        "customer_phone": customer_phone,
        "customer_city": customer_city,
        "customer_post_code": customer_post_code,
        "customer_email": customer_email,
        "client_ip": client_ip,
    }
    try:
        req = PaymentRequestModel(**payload)
    except TypeError:
        # Fallback: filter unknown keys via __init__ signature
        try:
            sig = inspect.signature(PaymentRequestModel)
            allowed = set(sig.parameters.keys())
            filtered = {k: v for k, v in payload.items() if k in allowed}
            req = PaymentRequestModel(**filtered)
        except Exception:
            # As a last resort, pass only the minimum required
            req = PaymentRequestModel(
                amount=amount, order_id=order_id, currency=currency
            )
    try:
        details = plugin.make_payment(req)
    except KeyError as exc:
        logger.warning(
            "shurjoPay plugin missing expected key during make_payment for %s: %s",
            order_id,
            exc,
            exc_info=True,
        )
        return None
    except (ShurjopayException, ShurjopayAuthException) as exc:
        logger.warning(
            "shurjoPay plugin error during make_payment for %s: %s",
            order_id,
            exc,
            exc_info=True,
        )
        return None
    except Exception:
        logger.exception("Unexpected shurjoPay failure for order %s", order_id)
        return None
    return details


def verify_payment(order_id: str):
    env = load_env()
    if env.verify_mode == "raw":
        raw = _raw_verify(order_id)
        return SimpleNamespace(**raw) if raw else None

    plugin = build_plugin()
    try:
        return plugin.verify_payment(order_id)
    except (ShurjopayException, ShurjopayAuthException, Exception) as e:
        # Be defensive: plugin may raise if response contains unexpected nulls.
        logging.getLogger(__name__).info(
            "SDK verify raised for %s; falling back: %s", order_id, e
        )
        if env.verify_mode in ("auto", "fallback"):
            try:
                raw = _raw_verify(order_id)
                if raw:
                    return SimpleNamespace(**raw)
            except Exception as e2:
                logging.getLogger(__name__).info(
                    "Raw ShurjoPay verify fallback failed for %s: %s", order_id, e2
                )
        return None


def _raw_get_token(endpoint: str, username: str, password: str) -> dict | None:
    base = endpoint.rstrip("/") + "/api/get_token"
    headers_json = {"Content-Type": "application/json"}
    headers_form = {"Content-Type": "application/x-www-form-urlencoded"}
    payload = {"username": username, "password": password}
    # Try JSON first
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(base, data=data, headers=headers_json, method="POST")
        with urlrequest.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    # Fallback to form-encoded
    try:
        data = urlparse.urlencode(payload).encode("utf-8")
        req = urlrequest.Request(base, data=data, headers=headers_form, method="POST")
        with urlrequest.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _raw_verify(order_id: str) -> dict | None:
    env = load_env()
    token_resp = _raw_get_token(env.endpoint, env.username, env.password)
    if not token_resp:
        return None
    token = (
        token_resp.get("token")
        or token_resp.get("access_token")
        or token_resp.get("id_token")
    )
    token_type = token_resp.get("token_type", "Bearer")
    if not token:
        return None
    url = env.endpoint.rstrip("/") + "/api/verification"
    headers = {
        "Authorization": f"{token_type} {token}",
        "Content-Type": "application/json",
    }
    body = {"order_id": order_id}
    data = json.dumps(body).encode("utf-8")
    req = urlrequest.Request(url, data=data, headers=headers, method="POST")
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            txt = resp.read().decode("utf-8")
            # Response could be a list (history) or object
            parsed = json.loads(txt)
            if isinstance(parsed, list):
                # Pick the latest (assuming last entry is most recent)
                return parsed[-1] if parsed else None
            return parsed
    except urlerror.HTTPError as he:
        # Try form-encoded as fallback
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        data = urlparse.urlencode(body).encode("utf-8")
        req = urlrequest.Request(url, data=data, headers=headers, method="POST")
        with urlrequest.urlopen(req, timeout=20) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            if isinstance(parsed, list):
                return parsed[-1] if parsed else None
            return parsed
