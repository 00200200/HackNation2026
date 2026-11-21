"""deploy/pull-deploy.sh with git, docker, curl and flock stubbed on PATH."""

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "deploy" / "pull-deploy.sh"


def test_a_failed_deploy_clears_the_record_of_the_last_good_one(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "flock": "exit 0",
        "git": 'case "$1" in rev-parse) echo commit-b;; log) echo "b msg";; esac',
        "docker": "exit 1",  # the new stack fails to start
        "curl": "exit 0",
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    (tmp_path / ".git").mkdir()
    deployed = tmp_path / ".git" / "deployed-commit"
    deployed.write_text("commit-a\n")
    script = tmp_path / "pull-deploy.sh"
    script.write_text(
        SCRIPT.read_text().replace("cd /opt/faktczyfejk", f"cd {tmp_path}")
    )

    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    run = subprocess.run(["sh", str(script)], check=False, env=env, capture_output=True)

    assert run.returncode != 0
    # Commit A is no longer marked as running, so a return of prod to A deploys it again.
    assert not deployed.exists()
