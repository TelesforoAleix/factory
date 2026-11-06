import os
from datetime import date, timedelta
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "node/bin/factory-export"


@pytest.fixture
def exporter(tmp_path):
    env_file = tmp_path / "runner.env"
    script = tmp_path / "factory-export"
    script.write_text(SCRIPT.read_text().replace("/etc/factory/runner.env", str(env_file)))
    script.chmod(0o755)
    fake = tmp_path / "factory-cplane"
    fake.write_text(
        "#!/bin/sh\n"
        "[ \"$1\" = export ] || exit 2\n"
        "printf state > \"$2\"\n"
        "printf notices > \"$2.outbox.jsonl\"\n"
        "[ \"${FAIL_EXPORT:-0}\" = 0 ]\n"
    )
    fake.chmod(0o755)

    def run(directory, *, fail=False, configured=True):
        env_file.write_text(f"CPLANE_EXPORT_DIR='{directory}'\n" if configured else "")
        env = os.environ | {"PATH": f"{tmp_path}:/usr/bin:/bin", "FAIL_EXPORT": str(int(fail))}
        env.pop("CPLANE_EXPORT_DIR", None)
        return subprocess.run([str(script)], env=env, capture_output=True, text=True)

    return run


def test_retains_seven_pairs_and_private_modes(exporter, tmp_path):
    directory = tmp_path / "exports"
    directory.mkdir()
    for days in range(1, 10):
        path = directory / f"factory-{date.today() - timedelta(days=days)}.json"
        path.write_text("old")
        Path(f"{path}.outbox.jsonl").write_text("old notices")
    result = exporter(directory)
    assert result.returncode == 0, result.stderr
    states = sorted(directory.glob("factory-*.json"))
    assert len(states) == 7
    assert states[0].name == f"factory-{date.today() - timedelta(days=6)}.json"
    assert len(list(directory.glob("*.outbox.jsonl"))) == 7
    today = directory / f"factory-{date.today()}.json"
    assert today.read_text() == "state"
    assert Path(f"{today}.outbox.jsonl").read_text() == "notices"
    assert today.stat().st_mode & 0o777 == 0o600
    assert Path(f"{today}.outbox.jsonl").stat().st_mode & 0o777 == 0o600


def test_missing_directory_fails_without_creating_it(exporter, tmp_path):
    directory = tmp_path / "missing"
    result = exporter(directory)
    assert result.returncode != 0
    assert "directory does not exist" in result.stderr
    assert not directory.exists()


def test_unset_directory_fails(exporter, tmp_path):
    result = exporter(tmp_path, configured=False)
    assert result.returncode != 0
    assert "CPLANE_EXPORT_DIR" in result.stderr


def test_failed_export_leaves_no_partial_files_or_deletes(exporter, tmp_path):
    directory = tmp_path / "exports"
    directory.mkdir()
    for days in range(10):
        path = directory / f"factory-{date.today() - timedelta(days=days)}.json"
        path.write_text("old")
        Path(f"{path}.outbox.jsonl").write_text("old notices")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    result = exporter(directory, fail=True)
    assert result.returncode != 0
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
