import numpy as np
import pandas as pd
import pytest

from portfolio_app.research_integrity import (
    IntegrityViolation, audit_research_input, audit_labels,
    temporal_split, check_fit_scope, assert_causal_prefix,
)


def bars(n=30):
    return pd.DataFrame(dict(trade_date=pd.date_range('2026-01-01', periods=n),
                             symbol='DEMO', close=np.arange(n) + 10.))


@pytest.mark.parametrize('column', ['feature_available_at', 'group_available_at',
    'adjustment_available_at', 'available_at'])
def test_future_information_is_rejected_with_readable_reason(column):
    frame = bars()
    frame[column] = frame.trade_date + pd.Timedelta(days=1)
    with pytest.raises(IntegrityViolation, match='晚于决策'):
        audit_research_input(frame)


def test_missing_metadata_is_disclosed_and_mixed_clock_is_not_guessed():
    assert audit_research_input(bars())['status'] == 'UNVERIFIED'
    frame = bars()
    frame['feature_available_at'] = frame.trade_date
    assert audit_research_input(frame)['status'] == 'DECLARED_TIMING_CHECKED'
    frame.loc[0, 'feature_available_at'] = pd.NaT
    with pytest.raises(IntegrityViolation, match='缺失'):
        audit_research_input(frame)


def test_tail_labels_cannot_be_filled_and_future_labels_cannot_be_features():
    frame = bars()
    frame['forward_label'] = frame.close.shift(-3) / frame.close - 1
    frame['label_available_at'] = frame.trade_date.shift(-3)
    assert audit_labels(frame, horizon=3)['incomplete_tail'] == 3
    corrupt = frame.copy()
    corrupt['forward_label'] = corrupt.forward_label.fillna(0)
    with pytest.raises(IntegrityViolation, match='尾部'):
        audit_labels(corrupt, horizon=3)
    with pytest.raises(IntegrityViolation, match='未来标签'):
        audit_research_input(frame, feature_fields=['forward_label'])


def test_split_purges_cross_boundary_labels_and_uses_horizon_embargo():
    dates = pd.date_range('2026-01-01', periods=50)
    split = temporal_split(dates, horizon=3, train_fraction=.5, validation_fraction=.2)
    assert split['embargo_sessions'] == 3
    assert max(split['train']) + 3 < min(split['validation'])
    assert max(split['validation']) + 3 < min(split['test'])
    assert split['purged_sessions'] == 6
    assert split['embargoed_sessions'] == 6
    assert check_fit_scope(split, fit_sessions=split['train'], tune_sessions=split['validation'], attempts=4)['attempts'] == 4
    with pytest.raises(IntegrityViolation, match='测试'):
        check_fit_scope(split, fit_sessions=split['train'], tune_sessions=split['test'], attempts=4)
    with pytest.raises(IntegrityViolation, match='训练'):
        check_fit_scope(split, fit_sessions=split['validation'], tune_sessions=[], attempts=1)


def test_prefix_counterexample_catches_future_shift_while_trailing_feature_passes():
    assert_causal_prefix(bars(), lambda f: f.close.rolling(3).mean(), checkpoints=[10, 20])
    with pytest.raises(IntegrityViolation, match='前缀'):
        assert_causal_prefix(bars(), lambda f: f.close.shift(-1), checkpoints=[10, 20])


def test_future_adjustment_and_group_declarations_cannot_be_hidden_in_attrs():
    frame = bars()
    frame.attrs['research_timing'] = {'price_mode': 'back_adjusted_latest'}
    with pytest.raises(IntegrityViolation, match='复权'):
        audit_research_input(frame)
    frame.attrs['research_timing'] = {'group_basis': 'future_label'}
    with pytest.raises(IntegrityViolation, match='分组'):
        audit_research_input(frame)
