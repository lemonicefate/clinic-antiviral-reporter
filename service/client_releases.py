"""Device-authorized desktop release distribution; contains no patient data."""

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from service.backup_archive import BackupError, reject_reparse, write_new
from service.settings import Settings
from service.storage import Store, saved_result, save_result


MAX_INSTALLER_BYTES = 128 * 1024 * 1024


def validate_version(value: str) -> str:
    if not re.fullmatch(r"(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})\.(0|[1-9][0-9]{0,4})", value):
        raise ValueError("Release version must be canonical major.minor.patch")
    if any(int(part) > 65535 for part in value.split(".")):
        raise ValueError("Release version components cannot exceed 65535")
    return value


class PublishRelease(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requestId: UUID
    expectedRevision: int = Field(ge=0, strict=True)
    version: str
    operator: str = Field(min_length=1, max_length=100, pattern=r"\S")
    reason: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    notes: str = Field(default="", max_length=4000)

    _version = field_validator("version")(validate_version)


class ReleaseView(BaseModel):
    version: str
    sha256: str
    size: int
    signature: str
    notes: str


class ReleaseStatus(BaseModel):
    revision: int
    release: ReleaseView | None


def release_view(row) -> dict:
    return {key: row[key] for key in ("version", "sha256", "size", "signature", "notes")}


def release_status(db) -> dict:
    row = db.execute("SELECT * FROM client_releases ORDER BY revision DESC LIMIT 1").fetchone()
    return {"revision": row["revision"] if row else 0, "release": release_view(row) if row else None}


def read_bounded(path: Path, limit: int) -> bytes:
    reject_reparse(path)
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if not content or len(content) > limit:
        raise ValueError("Release artifact is empty or too large")
    return content


def artifact_path(settings: Settings, sha256: str) -> Path:
    if not re.fullmatch("[a-f0-9]{64}", sha256):
        raise ValueError("Invalid release digest")
    return Path(settings.state_dir) / "immutable-artifacts" / "client-releases" / (sha256 + ".exe")


def publish_release(settings: Settings, command: PublishRelease, installer: Path, signature_file: Path) -> dict:
    """Offline maintenance command. Clients must verify signatures with their pinned key."""
    try:
        store = Store(Path(settings.state_dir))
    except (OSError, sqlite3.Error):
        raise ValueError("Central release state could not be safely opened") from None
    try:
        with store.transaction() as db:
            previous = saved_result(db, "release-tool", str(command.requestId))
            if previous is not None:
                return previous
            current = release_status(db)
            if command.expectedRevision != current["revision"]:
                raise ValueError("Release revision conflict: " + json.dumps(current))
            if db.execute("SELECT 1 FROM client_releases WHERE version=?", (command.version,)).fetchone():
                raise ValueError("Published release versions cannot be replaced")
            content = read_bounded(installer, MAX_INSTALLER_BYTES)
            signature = read_bounded(signature_file, 16384).decode("ascii").strip()
            if not signature:
                raise ValueError("Release signature is empty")
            digest = hashlib.sha256(content).hexdigest()
            destination = artifact_path(settings, digest)
            reject_reparse(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if read_bounded(destination, MAX_INSTALLER_BYTES) != content:
                    raise ValueError("Retained release artifact failed integrity validation")
            else:
                # Interrupted staging files are never advertised by the API. An
                # orphaned complete blob can be reused only after byte comparison.
                staging = destination.with_name(str(uuid4()) + ".partial")
                write_new(staging, content)
                os.rename(staging, destination)
            revision = current["revision"] + 1
            db.execute("INSERT INTO client_releases VALUES (?,?,?,?,?,?)",
                       (revision, command.version, digest, len(content), signature, command.notes))
            db.execute("INSERT INTO audit_events(kind,device_id,operator,occurred_at,changes) VALUES (?,?,?,?,?)",
                       ("client_release_published", "release-tool", command.operator, time.time(),
                        json.dumps({"before": current, "version": command.version, "sha256": digest,
                                    "reason": command.reason, "revision": revision})))
            return save_result(db, "release-tool", str(command.requestId), release_status(db))
    except (OSError, BackupError, UnicodeError):
        raise ValueError("Release files could not be safely read or published") from None
    except sqlite3.Error:
        raise ValueError("Release publication failed; no catalog change was committed") from None
    finally:
        store.close()


def register_client_release_routes(app: FastAPI, settings: Settings, authorized) -> None:
    @app.get("/api/v1/client-releases/current", response_model=ReleaseStatus,
             operation_id="currentClientRelease")
    def current(request: Request, authorization: Annotated[str | None, Header()] = None):
        with request.app.state.store.transaction() as db:
            authorized(db, authorization)
            return release_status(db)

    def find_release(request, authorization, version):
        with request.app.state.store.transaction() as db:
            authorized(db, authorization)
            row = db.execute("SELECT * FROM client_releases WHERE version=?", (version,)).fetchone()
            if row is None:
                raise HTTPException(404, "Client release not found")
            return release_view(row)

    @app.get("/api/v1/client-releases/{version}", response_model=ReleaseView, operation_id="getClientRelease")
    def get_release(version: str, request: Request, authorization: Annotated[str | None, Header()] = None):
        return find_release(request, authorization, version)

    @app.get("/api/v1/client-releases/{version}/installer", response_class=Response,
             responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}},
             operation_id="downloadClientRelease")
    def download(version: str, request: Request, authorization: Annotated[str | None, Header()] = None):
        release = find_release(request, authorization, version)
        try:
            content = read_bounded(artifact_path(settings, release["sha256"]), MAX_INSTALLER_BYTES)
            if len(content) != release["size"] or hashlib.sha256(content).hexdigest() != release["sha256"]:
                raise ValueError("Integrity failure")
        except (OSError, ValueError, BackupError):
            raise HTTPException(503, "Client release artifact unavailable") from None
        return Response(content, media_type="application/octet-stream", headers={"Cache-Control": "no-store"})
