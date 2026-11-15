from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def test_seven_models_and_eleven_curves_reconcile_with_source_metric_definitions():
    from portfolio_app.historical_result_audit import audit_published_results
    audit = audit_published_results(ROOT)
    assert audit['status'] == 'passed'
    assert len(audit['curves']) == 11
    assert len(audit['models']) == 7
    assert all(row['status'] == 'reconciled' for row in audit['curves'])
    assert all(row['classification'] == 'historical_aggregate_only' for row in audit['curves'])
    by_model = {r['model']: r for r in audit['models']}
    assert by_model['model2']['research_gate'] == 'review_required'
    assert by_model['model6']['research_gate'] == 'review_required'
    assert by_model['model7']['runtime_performance'] == 'unavailable'


def test_curve_tampering_is_reported_without_silently_replacing_historical_metrics(tmp_path):
    import json
    from portfolio_app.historical_result_audit import audit_published_results
    shutil.copytree(ROOT / 'public_evidence', tmp_path / 'public_evidence')
    path = tmp_path / 'public_evidence/curves/model1--base.json'
    record = json.loads(path.read_text(encoding='utf8'))
    record['points'][-1]['value'] *= 1.1
    path.write_text(json.dumps(record), encoding='utf8')
    audit = audit_published_results(tmp_path)
    assert audit['status'] == 'failed'
    row = next(r for r in audit['curves'] if r['file'] == path.name)
    assert row['status'] != 'reconciled'


def test_missing_curve_does_not_pass_a_smaller_inventory(tmp_path):
    from portfolio_app.historical_result_audit import audit_published_results
    shutil.copytree(ROOT / 'public_evidence', tmp_path / 'public_evidence')
    (tmp_path / 'public_evidence/curves/model3--all_oos.json').unlink()
    assert audit_published_results(tmp_path)['status'] == 'failed'
