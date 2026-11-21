import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("docker"), reason="needs Docker Compose CLI")
def test_local_source_store_does_not_change_production_database(tmp_path):
    # The production overlay's relevant settings, including the required backend dependency.
    overlay = tmp_path / "compose.prod.yaml"
    overlay.write_text("""
services:
  backend:
    depends_on:
      db:
        condition: service_healthy
  db:
    image: pgvector/pgvector:0.8.7-pg18
    environment:
      POSTGRES_USER: production
      POSTGRES_DB: production
      POSTGRES_PASSWORD: synthetic
    volumes:
      - db_data:/var/lib/postgresql
    configs:
      - source: db_extensions
        target: /docker-entrypoint-initdb.d/extensions.sql
    healthcheck:
      test: [CMD, pg_isready]
configs:
  db_extensions:
    content: CREATE EXTENSION IF NOT EXISTS vector;
volumes:
  db_data:
""")
    command = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-f",
        str(ROOT / "compose.yaml"),
    ]
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPOSE_")}
    local = subprocess.run(
        command + ["config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(json.loads(local.stdout)["services"]) == {"backend", "frontend"}
    merged = subprocess.run(
        command + ["-f", str(overlay), "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(merged.stdout)["services"]
    assert set(services) == {"backend", "frontend", "db"}
    db = services["db"]
    assert "ports" not in db and "profiles" not in db
    assert db["image"] == "pgvector/pgvector:0.8.7-pg18"
    assert db["environment"] == {
        "POSTGRES_USER": "production",
        "POSTGRES_DB": "production",
        "POSTGRES_PASSWORD": "synthetic",
    }
    assert [(v["source"], v["target"]) for v in db["volumes"]] == [
        ("db_data", "/var/lib/postgresql")
    ]
    assert db["configs"] == [
        {
            "source": "db_extensions",
            "target": "/docker-entrypoint-initdb.d/extensions.sql",
        }
    ]
    enabled = subprocess.run(
        command + ["--profile", "sourcedb", "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    source = json.loads(enabled.stdout)["services"]["sourcedb"]
    assert source["volumes"][0]["source"] == "sourcedb_data"


def test_seed_recipe_loads_dotenv_before_building_database_url(tmp_path):
    (tmp_path / ".env").write_text("POSTGRES_PASSWORD=synthetic\nDB_PORT=6543\n")
    recipe = subprocess.run(
        ["make", "-n", "-f", str(ROOT / "Makefile"), "db-seed"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "uv run --env-file .env python -m prawdowid.corpus --local-db" in recipe
    assert "DATABASE_URL=" not in recipe
    # Execute the recipe's uv/env loading with an assertion instead of seeding real pages.
    command = shlex.split(recipe)
    command[2:2] = ["--project", str(ROOT)]
    command[command.index("python") + 1 :] = [
        "-c",
        "from prawdowid.corpus import local_database_url; assert local_database_url() == 'postgresql://prawdowid:synthetic@127.0.0.1:6543/prawdowid'",
    ]
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"POSTGRES_PASSWORD", "DB_PORT", "DATABASE_URL"}
    }
    env["PYTHONPATH"] = str(ROOT)
    subprocess.run(
        command, cwd=tmp_path, env=env, capture_output=True, text=True, check=True
    )
