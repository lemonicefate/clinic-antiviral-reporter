"""Build two synthetic signed Windows releases. All keys/artifacts remain outside Git."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def prepare() -> Path:
    repo = Path(__file__).resolve().parents[1]
    client = repo / "client"
    cli = client / "node_modules/@tauri-apps/cli/tauri.js"
    if not cli.is_file():
        raise RuntimeError("Run npm ci in client before preparing signed test releases")
    root = Path(tempfile.mkdtemp(prefix="ClinicReporter Signed Updates ")).resolve()
    key = root / "synthetic.key"
    environment = dict(os.environ)

    def run(arguments: list[str], log: str):
        with (root / log).open("wb") as output:
            result = subprocess.run(["node", str(cli), *arguments], cwd=client, env=environment,
                                    stdout=output, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError("Synthetic preparation failed; inspect the private log: " + str(root / log))

    # Signer output can contain private key material; never forward it to stdout.
    run(["signer", "generate", "--ci", "--password", "synthetic-only", "--write-keys", str(key)], "signer-private.log")
    environment["CLINIC_REPORTER_UPDATE_PUBLIC_KEY"] = key.with_suffix(".key.pub").read_text().strip()
    releases = {}
    for version in ("0.1.0", "0.1.1"):
        print("Building synthetic desktop " + version, flush=True)
        configuration = root / (version + ".json")
        configuration.write_text(json.dumps({"version": version}), encoding="utf-8")
        run(["build", "--debug", "--bundles", "nsis", "--config", str(configuration)], "build-" + version + ".log")
        source = client / "src-tauri/target/debug/bundle/nsis" / ("公費抗病毒藥劑回報_" + version + "_x64-setup.exe")
        installer = root / (version + "-setup.exe")
        executable = root / (version + "-client.exe")
        shutil.copyfile(source, installer)
        shutil.copyfile(client / "src-tauri/target/debug/clinic-antiviral-reporter.exe", executable)
        run(["signer", "sign", "--private-key-path", str(key), "--password", "synthetic-only",
             "--app-version", version, str(installer)], "sign-" + version + ".log")
        releases[version] = {"installer": str(installer), "signature": str(installer) + ".sig", "executable": str(executable)}
    metadata = root / "releases.json"
    metadata.write_text(json.dumps({"syntheticOnly": True, "releases": releases}, indent=2), encoding="utf-8")
    print("Prepared synthetic release metadata: " + str(metadata), flush=True)
    return metadata


if __name__ == "__main__":
    prepare()
