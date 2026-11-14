from __future__ import annotations

from io import BytesIO
import json
import zipfile

import pytest

from portfolio_app.factor_research_archive import (
    FactorArchiveError,
    compare_factor_runs,
    copy_factor_config,
    open_factor_archive,
    save_factor_archive,
)


def config(label: str = "forward-5d", cost: float = 0.001) -> dict[str, object]:
    return {
        "factor_id": "basic.return_20d",
        "dataset_id": "demo_dataset",
        "data_version": "data-v1",
        "label_id": label,
        "processing_version": "proc-v1",
        "cost": cost,
        "disclosure_mode": "private_local",
        'date_start': '2026-01-01',
        'date_end': '2026-02-01',
    }


def result(label: str = "forward-5d", cost: float = 0.001, nav: float = 1.1) -> dict[str, object]:
    return {"config": config(label, cost), "metrics": {"ic_mean": 0.2, "nav": nav}, "engine_version": "1.0.0"}


def test_save_open_copy_archive_round_trip_and_checksum() -> None:
    archive = save_factor_archive(config(), result())
    manifest, copied_config, copied_result = open_factor_archive(archive)

    assert manifest["disclosure_mode"] == "private_local"
    assert manifest["config_sha256"]
    assert copied_config == config()
    assert copied_result == result()
    assert copy_factor_config(config(), name="copy")["config"]["label_id"] == "forward-5d"

    tampered_buffer = BytesIO()
    with zipfile.ZipFile(BytesIO(archive)) as source, zipfile.ZipFile(
        tampered_buffer, "w", compression=zipfile.ZIP_DEFLATED
    ) as target:
        for member in source.infolist():
            payload = source.read(member.filename)
            if member.filename == "result.json":
                changed_result = json.loads(payload)
                changed_result["metrics"]["nav"] = 9.9
                payload = json.dumps(
                    changed_result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            target.writestr(member.filename, payload)
    tampered = tampered_buffer.getvalue()
    with pytest.raises(FactorArchiveError, match="checksum"):
        open_factor_archive(tampered)


def test_comparison_requires_same_research_semantics() -> None:
    comparable = compare_factor_runs([result(nav=1.1), result(nav=1.2)])
    assert comparable["comparable"] is True
    assert comparable["rows"][0]["rank"] == 1

    with pytest.raises(FactorArchiveError, match="label"):
        compare_factor_runs([result("forward-5d"), result("forward-20d")])
    with pytest.raises(FactorArchiveError, match="cost"):
        compare_factor_runs([result(cost=0.001), result(cost=0.002)])
    changed = result()
    changed['engine_version'] = '2.0.0'
    with pytest.raises(FactorArchiveError, match='engine'):
        compare_factor_runs([result(), changed])
    missing = result()
    del missing['config']['date_start']
    with pytest.raises(FactorArchiveError, match='missing'):
        compare_factor_runs([result(), missing])


def test_archive_rejects_public_mode_and_private_material() -> None:
    private = config()
    private["source_path"] = "C:/private/notes.csv"
    with pytest.raises(FactorArchiveError, match="private"):
        save_factor_archive(private, result())

    public = config()
    public["disclosure_mode"] = "public_demo"
    with pytest.raises(FactorArchiveError, match="local"):
        save_factor_archive(public, result())
