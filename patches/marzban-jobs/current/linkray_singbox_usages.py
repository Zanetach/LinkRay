import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from pymysql.err import OperationalError
from sqlalchemy import and_, bindparam, insert, select, update
from sqlalchemy.sql.dml import Insert

from app import logger, scheduler
from app.db import GetDB
from app.db.models import Admin, NodeUserUsage, System, User
from app.models.user import UserStatus
from config import (
    DISABLE_RECORDING_NODE_USAGE,
    JOB_RECORD_NODE_USAGES_INTERVAL,
    JOB_RECORD_USER_USAGES_INTERVAL,
)
from xray_api import XRay as XRayAPI
from xray_api import exc as xray_exc


LINKRAY_SINGBOX_STATS_API = os.getenv("LINKRAY_SINGBOX_STATS_API", "127.0.0.1:61996")
LINKRAY_SINGBOX_SIDECAR_URL = os.getenv("LINKRAY_SINGBOX_SIDECAR_URL", "http://127.0.0.1:61995")
LINKRAY_SNELL_USAGE_URL = os.getenv("LINKRAY_SNELL_USAGE_URL", "http://127.0.0.1:61997")


def _stats_endpoint() -> Optional[tuple[str, int]]:
    value = LINKRAY_SINGBOX_STATS_API.strip()
    if not value:
        return None
    host, _, raw_port = value.rpartition(":")
    if not host or not raw_port:
        logger.warning("Invalid LINKRAY_SINGBOX_STATS_API=%r", value)
        return None
    try:
        return host, int(raw_port)
    except ValueError:
        logger.warning("Invalid LINKRAY_SINGBOX_STATS_API port in %r", value)
        return None


def _singbox_api() -> Optional[XRayAPI]:
    endpoint = _stats_endpoint()
    if not endpoint:
        return None
    host, port = endpoint
    return XRayAPI(address=host, port=port)


def _safe_execute(db, stmt, params=None):
    if db.bind.name == "mysql":
        if isinstance(stmt, Insert):
            stmt = stmt.prefix_with("IGNORE")

        tries = 0
        while True:
            try:
                db.connection().execute(stmt, params)
                db.commit()
                return
            except OperationalError as err:
                if err.args[0] == 1213 and tries < 3:
                    db.rollback()
                    tries += 1
                    continue
                raise err

    db.connection().execute(stmt, params)
    db.commit()


def _username_stats(api: XRayAPI) -> dict[str, int]:
    usage = defaultdict(int)
    for stat in api.get_users_stats(reset=True, timeout=30):
        if stat.value:
            usage[stat.name] += stat.value
    return dict(usage)


def _snell_usage_stats() -> dict[str, int]:
    if not LINKRAY_SNELL_USAGE_URL:
        return {}
    request = Request(
        f"{LINKRAY_SNELL_USAGE_URL.rstrip('/')}/usage/collect",
        data=b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError) as err:
        logger.warning("LinkRay Snell usage collection failed: %s", err)
        return {}

    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}

    parsed: dict[str, int] = {}
    for username, value in usage.items():
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if isinstance(username, str) and amount > 0:
            parsed[username] = parsed.get(username, 0) + amount
    return parsed


def _user_params(username_usage: dict[str, int]) -> list[dict[str, int]]:
    if not username_usage:
        return []

    usernames = set(username_usage)
    with GetDB() as db:
        rows = db.query(User.username, User.id).filter(User.username.in_(usernames)).all()
    username_to_id = {username: user_id for username, user_id in rows}

    params = []
    for username, value in username_usage.items():
        user_id = username_to_id.get(username)
        if user_id:
            params.append({"uid": int(user_id), "value": int(value)})
    return params


def _active_usernames() -> list[str]:
    with GetDB() as db:
        rows = db.query(User.username).filter(User.status == UserStatus.active).all()
    return sorted(username for (username,) in rows if username)


def reconcile_linkray_singbox_runtime_users():
    if not LINKRAY_SINGBOX_SIDECAR_URL:
        return
    body = json.dumps({"active_usernames": _active_usernames()}).encode("utf-8")
    request = Request(
        f"{LINKRAY_SINGBOX_SIDECAR_URL.rstrip('/')}/runtime/reconcile",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            response.read()
    except (OSError, URLError, ValueError) as err:
        logger.warning("LinkRay sing-box runtime reconcile failed: %s", err)


def _record_user_hourly_stats(params: list[dict[str, int]]) -> None:
    if not params or DISABLE_RECORDING_NODE_USAGE:
        return

    created_at = datetime.fromisoformat(datetime.utcnow().strftime("%Y-%m-%dT%H:00:00"))
    with GetDB() as db:
        select_stmt = select(NodeUserUsage.user_id).where(
            and_(NodeUserUsage.node_id.is_(None), NodeUserUsage.created_at == created_at)
        )
        existing = {row[0] for row in db.execute(select_stmt).fetchall()}
        missing = {param["uid"] for param in params if param["uid"] not in existing}
        if missing:
            stmt = insert(NodeUserUsage).values(
                user_id=bindparam("uid"),
                created_at=created_at,
                node_id=None,
                used_traffic=0,
            )
            _safe_execute(db, stmt, [{"uid": uid} for uid in missing])

        stmt = (
            update(NodeUserUsage)
            .values(used_traffic=NodeUserUsage.used_traffic + bindparam("value"))
            .where(
                and_(
                    NodeUserUsage.user_id == bindparam("uid"),
                    NodeUserUsage.node_id.is_(None),
                    NodeUserUsage.created_at == created_at,
                )
            )
        )
        _safe_execute(db, stmt, params)


def record_linkray_singbox_user_usages():
    api = _singbox_api()
    if not api:
        return
    try:
        params = _user_params(_username_stats(api))
    except xray_exc.XrayError:
        return

    if not params:
        return

    _record_user_usage_params(params)


def _record_user_usage_params(params: list[dict[str, int]]) -> None:
    with GetDB() as db:
        user_admin_map = dict(db.query(User.id, User.admin_id).all())

    admin_usage = defaultdict(int)
    for item in params:
        admin_id = user_admin_map.get(item["uid"])
        if admin_id:
            admin_usage[admin_id] += item["value"]

    with GetDB() as db:
        stmt = (
            update(User)
            .where(User.id == bindparam("uid"))
            .values(
                used_traffic=User.used_traffic + bindparam("value"),
                online_at=datetime.utcnow(),
            )
        )
        _safe_execute(db, stmt, params)

        admin_params = [{"admin_id": admin_id, "value": value} for admin_id, value in admin_usage.items()]
        if admin_params:
            admin_stmt = (
                update(Admin)
                .where(Admin.id == bindparam("admin_id"))
                .values(users_usage=Admin.users_usage + bindparam("value"))
            )
            _safe_execute(db, admin_stmt, admin_params)

    _record_user_hourly_stats(params)


def record_linkray_snell_user_usages():
    params = _user_params(_snell_usage_stats())
    if not params:
        return
    _record_user_usage_params(params)


def record_linkray_singbox_node_usages():
    api = _singbox_api()
    if not api:
        return
    try:
        up = 0
        down = 0
        for stat in api.get_outbounds_stats(reset=True, timeout=10):
            if stat.link == "uplink":
                up += stat.value
            elif stat.link == "downlink":
                down += stat.value
    except xray_exc.XrayError:
        return

    if not (up or down):
        return

    with GetDB() as db:
        stmt = update(System).values(uplink=System.uplink + up, downlink=System.downlink + down)
        _safe_execute(db, stmt)


scheduler.add_job(
    reconcile_linkray_singbox_runtime_users,
    "interval",
    seconds=JOB_RECORD_USER_USAGES_INTERVAL,
    coalesce=True,
    max_instances=1,
    id="linkray_singbox_runtime_reconcile",
)
scheduler.add_job(
    record_linkray_singbox_user_usages,
    "interval",
    seconds=JOB_RECORD_USER_USAGES_INTERVAL,
    coalesce=True,
    max_instances=1,
    id="linkray_singbox_user_usages",
)
scheduler.add_job(
    record_linkray_snell_user_usages,
    "interval",
    seconds=JOB_RECORD_USER_USAGES_INTERVAL,
    coalesce=True,
    max_instances=1,
    id="linkray_snell_user_usages",
)
scheduler.add_job(
    record_linkray_singbox_node_usages,
    "interval",
    seconds=JOB_RECORD_NODE_USAGES_INTERVAL,
    coalesce=True,
    max_instances=1,
    id="linkray_singbox_node_usages",
)
