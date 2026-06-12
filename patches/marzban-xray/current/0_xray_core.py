import os
import time
import traceback
from pathlib import Path

from app import app, logger, scheduler, xray
from app.db import GetDB, crud
from app.models.node import NodeStatus
from app.models.user import UserStatus
from config import JOB_CORE_HEALTH_CHECK_INTERVAL
from xray_api import exc as xray_exc


LINKRAY_EXTERNAL_XRAY = os.getenv("LINKRAY_EXTERNAL_XRAY", "").strip().lower() in {"1", "true", "yes", "on"}
LINKRAY_XRAY_RUNTIME_CONFIG = os.getenv(
    "LINKRAY_XRAY_RUNTIME_CONFIG",
    "/var/lib/marzban/linkray/xray/runtime.json",
)


def _write_external_runtime_config(config):
    path = Path(LINKRAY_XRAY_RUNTIME_CONFIG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.to_json(indent=2) + "\n", encoding="utf-8")


def _sync_external_main_core_users():
    with GetDB() as db:
        users = crud.get_users(db, status=[UserStatus.active, UserStatus.on_hold])
        for dbuser in users:
            xray.operations.add_user(dbuser)


def _external_main_core_health_check(config):
    _write_external_runtime_config(config)
    try:
        xray.api.get_sys_stats(timeout=2)
    except (ConnectionError, xray_exc.XrayError) as exc:
        logger.warning("LinkRay external Xray API is not ready: %s", exc)
        return
    _sync_external_main_core_users()


def core_health_check():
    config = None

    # main core
    if LINKRAY_EXTERNAL_XRAY:
        if not config:
            config = xray.config.include_db_users()
        _external_main_core_health_check(config)
    elif not xray.core.started:
        if not config:
            config = xray.config.include_db_users()
        xray.core.restart(config)

    # nodes' core
    for node_id, node in list(xray.nodes.items()):
        if node.connected:
            try:
                assert node.started
                node.api.get_sys_stats(timeout=2)
            except (ConnectionError, xray_exc.XrayError, AssertionError):
                if not config:
                    config = xray.config.include_db_users()
                xray.operations.restart_node(node_id, config)

        if not node.connected:
            if not config:
                config = xray.config.include_db_users()
            xray.operations.connect_node(node_id, config)


@app.on_event("startup")
def start_core():
    logger.info("Generating Xray core config")

    start_time = time.time()
    config = xray.config.include_db_users()
    logger.info(f"Xray core config generated in {(time.time() - start_time):.2f} seconds")

    # main core
    if LINKRAY_EXTERNAL_XRAY:
        logger.info("Using LinkRay-managed external Xray core")
        try:
            _write_external_runtime_config(config)
            _sync_external_main_core_users()
        except Exception:
            traceback.print_exc()
    else:
        logger.info("Starting main Xray core")
        try:
            xray.core.start(config)
        except Exception:
            traceback.print_exc()

    # nodes' core
    logger.info("Starting nodes Xray core")
    with GetDB() as db:
        dbnodes = crud.get_nodes(db=db, enabled=True)
        node_ids = [dbnode.id for dbnode in dbnodes]
        for dbnode in dbnodes:
            crud.update_node_status(db, dbnode, NodeStatus.connecting)

    for node_id in node_ids:
        xray.operations.connect_node(node_id, config)

    scheduler.add_job(
        core_health_check,
        "interval",
        seconds=JOB_CORE_HEALTH_CHECK_INTERVAL,
        coalesce=True,
        max_instances=1,
    )


@app.on_event("shutdown")
def app_shutdown():
    if LINKRAY_EXTERNAL_XRAY:
        logger.info("Leaving LinkRay-managed external Xray core running")
    else:
        logger.info("Stopping main Xray core")
        xray.core.stop()

    logger.info("Stopping nodes Xray core")
    for node in list(xray.nodes.values()):
        try:
            node.disconnect()
        except Exception:
            pass
