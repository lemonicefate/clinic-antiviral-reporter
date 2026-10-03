"""Run real-API browser checks in a fresh, disposable synthetic environment."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import ProxyHandler, Request, build_opener


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    temporary = tempfile.TemporaryDirectory(prefix="clinic-synthetic-e2e-")
    with temporary as directory:
        environment = dict(os.environ, LOCALAPPDATA=directory)
        process = subprocess.Popen([sys.executable, "-m", "scripts.acceptance_environment"],
                                   cwd=repo, env=environment, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            metadata = Path(directory) / "ClinicReporterAcceptance/case-queue-v1/current.json"
            opener = build_opener(ProxyHandler({}))
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError("Synthetic acceptance service failed to start")
                if metadata.is_file():
                    url = json.loads(metadata.read_text())["url"]
                    with opener.open(url + "status", timeout=5) as response:
                        if json.load(response)["running"]:
                            break
                time.sleep(0.1)
            else:
                raise RuntimeError("Synthetic acceptance startup timed out")
            for script in ("case-queue.cjs", "reasons.cjs"):
                subprocess.run(["node", str(repo / "client/e2e-real" / script)], cwd=repo / "client",
                               env=environment, check=True, timeout=120)
        finally:
            # Graceful quit joins Uvicorn and closes SQLite before the Windows
            # venv launcher exits. Terminating the launcher alone can race its child.
            if process.poll() is None:
                if metadata.is_file():
                    owned_url = json.loads(metadata.read_text())["url"]
                    with opener.open(owned_url, timeout=5) as response:
                        page = response.read().decode("utf-8")
                    match = re.search(r'const token=("[A-Za-z0-9_-]+")', page)
                    if not match:
                        raise RuntimeError("Owned harness shutdown token unavailable")
                    request = Request(owned_url + "control", method="POST", data=b'{"action":"quit"}',
                                      headers={"Content-Type": "application/json",
                                               "X-Acceptance": json.loads(match.group(1))})
                    with opener.open(request, timeout=15) as response:
                        if response.status != 200:
                            raise RuntimeError("Owned harness did not stop")
                else:
                    process.terminate()
            process.wait(timeout=15)
            for attempt in range(30):
                try:
                    temporary.cleanup()
                    break
                except PermissionError:
                    if attempt == 29:
                        raise
                    time.sleep(0.1)


if __name__ == "__main__":
    main()
