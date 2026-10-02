"""Offline first-device provisioning, under the same exclusive ownership lock."""

import json
import re
from pathlib import Path
import time
from uuid import uuid4

from service.settings import Settings
from service.storage import Store, digest


def initialize_administrator(settings: Settings, name: str, credential: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", credential) or not name.strip() or len(name) > 100:
        raise ValueError("Provide a device name and a randomly generated 256-bit credential")
    store = Store(Path(settings.state_dir))
    try:
        with store.transaction() as db:
            if db.execute("SELECT 1 FROM devices LIMIT 1").fetchone():
                raise ValueError("Initial administrator already provisioned")
            device_id = str(uuid4())
            db.execute("INSERT INTO devices VALUES (?,?,?,?,1,0)", (device_id, name, digest(credential), '["admin"]'))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("administrator_initialized", device_id, "local-provisioning", time.time(),
                        json.dumps({"name": name, "capabilities": ["admin"]})))
            return device_id
    finally:
        store.close()
