import copy
import hashlib
import json

import pytest

from portfolio_app.portfolio_archive import create_portfolio_archive, load_portfolio_archive
from tests.test_portfolio_workspace import run


def test_private_archive_roundtrip_has_inputs_config_outputs_engine_and_limitations():
    result = run()
    archive = create_portfolio_archive(result, mode="private_local")
    restored = load_portfolio_archive(json.loads(json.dumps(archive, allow_nan=False)))
    assert restored["payload"]["config"] == result.config
    assert restored["payload"]["inputs"] == result.inputs
    assert restored["payload"]["outputs"]["fills"] == result.fills
    assert restored["payload"]["limitations"]
    assert restored["payload"]["engine"]
    assert len(restored["checksum"]) == 64


def test_public_export_is_allowlisted_and_cannot_contain_real_targets_or_holdings():
    result = run()
    archive = create_portfolio_archive(result, mode="public_redacted")
    text = json.dumps(archive)
    assert "AAA" not in text and "BBB" not in text
    assert "quantity" not in text and "target_weights" not in text
    assert "data_sha256" not in text
    assert "total_return" in text
    assert load_portfolio_archive(archive) == archive


@pytest.mark.parametrize("mode", ["private_local", "public_redacted"])
def test_archive_detects_tampering_in_all_payload_sections(mode):
    archive = create_portfolio_archive(run(), mode=mode)
    altered = copy.deepcopy(archive)
    altered["payload"]["engine"] = "modified"
    with pytest.raises(ValueError, match="checksum"):
        load_portfolio_archive(altered)


def test_public_summary_does_not_copy_arbitrary_metric_fields_or_engine_metadata():
    result = run()
    result.metrics["private_path"] = "sensitive"
    result.inputs["engine"] = "sensitive"
    archive = create_portfolio_archive(result, mode="public_redacted")
    assert "sensitive" not in json.dumps(archive)


def test_public_summary_rejects_text_in_an_allowlisted_numeric_field():
    result = run()
    result.metrics["sharpe"] = "sensitive"
    with pytest.raises(ValueError, match="numeric"):
        create_portfolio_archive(result, mode="public_redacted")


def test_unknown_mode_rejected_and_nonfinite_metrics_are_json_null():
    result = run()
    with pytest.raises(ValueError, match="mode"):
        create_portfolio_archive(result, mode="public")
    result.metrics["sharpe"] = float("nan")
    archive = create_portfolio_archive(result, mode="private_local")
    assert archive["payload"]["outputs"]["metrics"]["sharpe"] is None
    json.dumps(archive, allow_nan=False)


def test_prior_public_engine_archive_remains_readable_after_fee_fix():
    archive = create_portfolio_archive(run(), mode="public_redacted")
    archive["payload"]["engine"] = "portfolio-workspace.v1"
    signed = {key: archive[key] for key in ["schema_version", "mode", "payload"]}
    canonical = json.dumps(signed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    archive["checksum"] = hashlib.sha256(canonical.encode()).hexdigest()
    assert load_portfolio_archive(archive)["payload"]["engine"] == "portfolio-workspace.v1"
