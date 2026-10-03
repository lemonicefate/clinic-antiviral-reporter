"""Generate a pinned, secret-free WinSW bundle for the central Windows service."""

import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import xml.etree.ElementTree as ET


PINNED_WINSW_VERSION = "2.12.0"
PINNED_WINSW_SHA256 = "05B82D46AD331CC16BDC00DE5C6332C1EF818DF8CEEFCD49C726553209B3A0DA"
SERVICE_ID = "ClinicAntiviralReporter"


@dataclass(frozen=True)
class ServiceBundle:
    output: Path
    release_root: Path
    python: Path
    environment: Path
    certificate: Path
    private_key: Path
    winsw: Path


def _reject_reparse(path: Path) -> None:
    for item in (path, *path.parents):
        try:
            metadata = os.lstat(item)
        except FileNotFoundError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        if stat.S_ISLNK(metadata.st_mode) or attributes & 0x400:
            raise ValueError(f"Service paths cannot contain links or reparse points: {item}")


def _existing(path: Path, *, directory: bool = False) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute path: {path}")
    _reject_reparse(path)
    resolved = path.resolve(strict=True)
    if directory and not resolved.is_dir():
        raise ValueError(f"Expected a directory: {path}")
    if not directory and (not resolved.is_file() or resolved.stat().st_size == 0):
        raise ValueError(f"Expected a non-empty file: {path}")
    return resolved


def _output(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError(f"Use an absolute output path: {path}")
    _reject_reparse(path)
    if path.exists():
        raise ValueError(f"Output already exists; preserve it and choose a new versioned path: {path}")
    parent = path.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError(f"Output parent is not a directory: {parent}")
    return parent / path.name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _configuration(bundle: ServiceBundle) -> ET.Element:
    root = ET.Element("service")
    values = (
        ("id", SERVICE_ID),
        ("name", "Clinic Antiviral Reporter Central Service"),
        ("description", "Single-owner HTTPS central service for the clinic antiviral reporter."),
        ("executable", str(bundle.python)),
        ("arguments", subprocess.list2cmdline([
            "-m", "service", "--env-file", str(bundle.environment), "serve",
            "--cert", str(bundle.certificate), "--key", str(bundle.private_key),
        ])),
        ("workingdirectory", str(bundle.release_root)),
        ("startmode", "Automatic"),
    )
    for name, value in values:
        ET.SubElement(root, name).text = value
    ET.SubElement(root, "delayedAutoStart")
    ET.SubElement(root, "stoptimeout").text = "30 sec"
    ET.SubElement(root, "stopparentprocessfirst").text = "true"
    ET.SubElement(root, "onfailure", {"action": "restart", "delay": "10 sec"})
    ET.SubElement(root, "resetfailure").text = "1 hour"
    ET.SubElement(root, "logpath").text = "%BASE%\\logs"
    ET.SubElement(root, "log", {"mode": "roll"})
    ET.indent(root, space="  ")
    return root


def create_bundle(bundle: ServiceBundle, *, expected_winsw_sha256: str = PINNED_WINSW_SHA256) -> Path:
    output = _output(bundle.output)
    release = _existing(bundle.release_root, directory=True)
    python = _existing(bundle.python)
    environment = _existing(bundle.environment)
    certificate = _existing(bundle.certificate)
    private_key = _existing(bundle.private_key)
    winsw = _existing(bundle.winsw)
    if not python.is_relative_to(release):
        raise ValueError("The service Python runtime must be inside the versioned release root")
    actual_digest = _sha256(winsw)
    expected_digest = expected_winsw_sha256.upper()
    if actual_digest != expected_digest:
        raise ValueError(f"WinSW SHA-256 mismatch: expected {expected_digest}, got {actual_digest}")

    resolved = ServiceBundle(output, release, python, environment, certificate, private_key, winsw)
    with tempfile.TemporaryDirectory(prefix=".central-service-pending-", dir=output.parent) as staging_name:
        staging = Path(staging_name)
        (staging / "logs").mkdir()
        shutil.copyfile(winsw, staging / "central-service.exe")
        tree = ET.ElementTree(_configuration(resolved))
        tree.write(staging / "central-service.xml", encoding="utf-8", xml_declaration=True)
        (staging / "README.txt").write_text(
            "\n".join((
                "Clinic Antiviral Reporter central service bundle",
                f"WinSW version: {PINNED_WINSW_VERSION}",
                f"Pinned WinSW SHA-256: {PINNED_WINSW_SHA256}",
                f"Verified wrapper SHA-256: {actual_digest}",
                "",
                "This bundle contains paths but no account password or application credential.",
                "Configure the dedicated Windows service account and ACLs before starting it.",
                "Run from an elevated PowerShell in this directory:",
                "  .\\central-service.exe install",
                "  .\\central-service.exe status",
                "  .\\central-service.exe start",
                "  .\\central-service.exe stop",
                "  .\\central-service.exe uninstall",
                "",
            )), encoding="utf-8")
        staging.rename(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--cert", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--winsw", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = create_bundle(ServiceBundle(args.output, args.release_root, args.python,
                                              args.env_file, args.cert, args.key, args.winsw))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
    print(f"Prepared central service bundle: {output}")


if __name__ == "__main__":
    main()
