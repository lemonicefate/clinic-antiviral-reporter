"""Explicit Windows service entry point; no current-directory config discovery."""

import argparse
import getpass
import json
import os
from pathlib import Path

from dotenv import dotenv_values
import uvicorn

from service.app import create_app
from service.provision import initialize_administrator
from service.settings import Settings, SettingsError
from service.client_releases import PublishRelease, publish_release


def absolute_file(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise argparse.ArgumentTypeError("Use an existing absolute file path")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Clinic central service")
    parser.add_argument("--env-file", type=absolute_file)
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser("provision", help="Initialize the first admin while the service is stopped")
    provision.add_argument("--name", required=True)
    serve = commands.add_parser("serve", help="Start one HTTPS central service process")
    serve.add_argument("--cert", required=True, type=absolute_file)
    serve.add_argument("--key", required=True, type=absolute_file)
    release = commands.add_parser("stage-release", help="Publish a desktop release while the service is stopped")
    release.add_argument("--version", required=True)
    release.add_argument("--installer", required=True, type=absolute_file)
    release.add_argument("--signature", required=True, type=absolute_file)
    release.add_argument("--operator", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--request-id", required=True)
    release.add_argument("--expected-revision", required=True, type=int)
    release.add_argument("--notes", default="")
    args = parser.parse_args()
    environment = dict(os.environ)
    if args.env_file:
        # Explicit environment variables override the explicitly selected file.
        environment = {key: value for key, value in dotenv_values(args.env_file, interpolate=False).items()
                       if value is not None} | environment
    try:
        settings = Settings.from_environment(environment)
        if args.command == "provision":
            credential = getpass.getpass("Device credential (43-character random base64url, hidden): ")
            initialize_administrator(settings, args.name, credential)
            print("Initial administrator provisioned. Device credential was not printed or logged.")
        elif args.command == "stage-release":
            command = PublishRelease(requestId=args.request_id, expectedRevision=args.expected_revision,
                                     version=args.version, operator=args.operator, reason=args.reason, notes=args.notes)
            print(json.dumps(publish_release(settings, command, args.installer, args.signature)))
        else:
            uvicorn.run(create_app(settings, tls_files=(args.cert, args.key)), host=settings.bind_host, port=settings.bind_port,
                        workers=1, proxy_headers=False, access_log=False,
                        ssl_certfile=str(args.cert), ssl_keyfile=str(args.key))
    except (SettingsError, ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
