"""install_dock idempotency + global.ini round-trip."""

from __future__ import annotations

import configparser
import json
from pathlib import Path

from open_spark.scripts.install_dock import install


def _read_entries(path: Path) -> list[dict]:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    return json.loads(cp["BasicWindow"]["ExtraBrowserDocks"])


def test_install_creates_entry(tmp_path: Path):
    install(name="Open Spark", url="http://127.0.0.1:8765", config_dir=tmp_path)
    entries = _read_entries(tmp_path / "global.ini")
    assert any(e["title"] == "Open Spark" for e in entries)


def test_install_idempotent(tmp_path: Path):
    install(config_dir=tmp_path)
    install(config_dir=tmp_path)
    entries = _read_entries(tmp_path / "global.ini")
    spark_entries = [e for e in entries if e["title"] == "Open Spark"]
    assert len(spark_entries) == 1


def test_install_preserves_other_docks(tmp_path: Path):
    ini = tmp_path / "global.ini"
    ini.write_text(
        '[BasicWindow]\nExtraBrowserDocks=[{"title": "Other", "url": "http://x", "uuid": ""}]\n',
        encoding="utf-8",
    )
    install(config_dir=tmp_path)
    entries = _read_entries(ini)
    titles = {e["title"] for e in entries}
    assert {"Other", "Open Spark"} <= titles
