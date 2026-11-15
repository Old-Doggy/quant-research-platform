"""Independent arithmetic for future integration; no engine claims here."""
import json
from pathlib import Path
from decimal import Decimal as D

CASES = json.loads((Path(__file__).parent / 'fixtures/research_truth/cases.json').read_text(encoding='utf-8'))


def test_truth_cases_are_explicit_and_cover_required_research_boundaries():
    assert CASES['purpose'] == 'synthetic_test_only'
    assert {c['kind'] for c in CASES['cases']} == {
        'cash_dividend', 'bonus_share', 'suspension', 'delisting', 'financial_revision', 'etf_rules'}
    assert len({c['id'] for c in CASES['cases']}) == 6
    assert all(c['input'] and c['expected'] and c['formula'] and c['status'] for c in CASES['cases'])


def test_cash_dividend_and_bonus_expectations_are_independently_balanced():
    cash, bonus = CASES['cases'][:2]
    i, e = cash['input'], cash['expected']
    assert D(i['shares']) * D(str(i['ex_close'])) + D(i['initial_cash']) + D(e['receivable']) == D(e['ex_equity'])
    assert e['payment_cash'] == i['initial_cash'] + e['receivable']
    assert e['initial_equity'] == e['ex_equity']
    i, e = bonus['input'], bonus['expected']
    assert D(i['shares']) * (1 + D(str(i['bonus_ratio']))) == D(e['total_shares'])
    assert e['unit_cost'] * e['total_shares'] == e['total_cost'] == i['total_cost']
    assert e['available_before_listing'] + e['locked_shares'] == e['available_after_listing']
