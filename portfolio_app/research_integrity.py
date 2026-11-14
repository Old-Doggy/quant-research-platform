"""Information-time checks and session-based purged temporal partitions.

Missing provenance is UNVERIFIED, never proof of PIT correctness. Prefix probes
are regression checks at declared cutoffs, not a proof for arbitrary programs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


class IntegrityViolation(ValueError):
    """Research would use information outside its allowed scope."""


def audit_research_input(frame, *, feature_fields=()):
    if frame.empty or 'trade_date' not in frame:
        raise IntegrityViolation('缺少决策日期或输入为空')
    if any('label' in str(field).lower() or str(field).startswith('forward_') for field in feature_fields):
        raise IntegrityViolation('未来标签不能作为决策特征')
    declarations = frame.attrs.get('research_timing', {})
    if declarations.get('price_mode') in {'back_adjusted_latest', 'future_adjusted'}:
        raise IntegrityViolation('复权使用了未来公司行为，不能通过历史时点检查')
    if declarations.get('group_basis') in {'future_label', 'full_sample_target'}:
        raise IntegrityViolation('分组使用未来标签或全样本目标')
    checked = []
    for field in set(feature_fields) & {'roe', 'pb', 'pe_ttm', 'dv_ratio', 'dt_netprofit_yoy', 'holder_num'}:
        if field + '_available_at' not in frame and 'feature_available_at' not in frame:
            raise IntegrityViolation('财务与股东特征缺少可用时点：' + field)
    decision_column = 'decision_at' if 'decision_at' in frame else 'trade_date'
    # Preserve clock semantics: UTC metadata needs an explicit timezone-aware
    # decision_at. Never silently interpret a daily session date as a close time.
    try:
        decision = pd.to_datetime(frame[decision_column], errors='raise')
        if decision.isna().any():
            raise ValueError('missing decision')
        for field in ('available_at', 'feature_available_at', 'group_available_at',
                      'adjustment_available_at', 'roe_available_at', 'pb_available_at',
                      *[f + '_available_at' for f in feature_fields if f + '_available_at' not in {'roe_available_at', 'pb_available_at'}]):
            if field not in frame:
                continue
            available = pd.to_datetime(frame[field], errors='raise')
            if available.isna().any():
                raise IntegrityViolation('可用时点缺失，无法核验')
            if (available > decision).any():
                raise IntegrityViolation('信息可用时点晚于决策：' + field)
            checked.append(field)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, IntegrityViolation):
            raise
        raise IntegrityViolation('决策与可用时点格式或时区不一致') from exc
    return dict(status='DECLARED_TIMING_CHECKED' if checked else 'UNVERIFIED',
                checked_fields=checked,
                limitations=['仅检查已声明的时点；缺少时点、历史成分或公司行为来源时，不能证明真实市场 PIT。',
                             '重叠收益为描述性统计，不提供默认独立样本 t 检验。'])


def audit_labels(frame, *, horizon):
    if type(horizon) is not int or horizon < 1:
        raise IntegrityViolation('标签跨度必须为正会话数')
    if not {'symbol', 'trade_date', 'forward_label', 'label_available_at'} <= set(frame):
        raise IntegrityViolation('标签字段不完整')
    tails = 0
    for _, group in frame.groupby('symbol', sort=False):
        group = group.sort_values('trade_date')
        expected = pd.to_datetime(group.trade_date).shift(-horizon)
        available = pd.to_datetime(group.label_available_at)
        tail = expected.isna()
        if group.loc[tail, 'forward_label'].notna().any() or available.loc[tail].notna().any():
            raise IntegrityViolation('尾部标签尚未成熟，不能填零或伪造可用时点')
        if not (available.loc[~tail].to_numpy() == expected.loc[~tail].to_numpy()).all():
            raise IntegrityViolation('标签可用时点与持有跨度不一致')
        tails += int(tail.sum())
    return dict(status='CHECKED', incomplete_tail=tails, horizon_sessions=horizon,
                inference='descriptive_only_overlapping_labels')


def temporal_split(sessions, *, horizon, train_fraction=.6, validation_fraction=.2):
    """Indices into explicit ordered sessions; purge then embargo at both borders."""
    dates = pd.DatetimeIndex(sessions)
    if dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise IntegrityViolation('切分需要有序且唯一的实际会话')
    if type(horizon) is not int or horizon < 1:
        raise IntegrityViolation('持有跨度无效')
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1 or train_fraction + validation_fraction >= 1:
        raise IntegrityViolation('切分比例无效')
    n = len(dates)
    first, second = int(n * train_fraction), int(n * (train_fraction + validation_fraction))
    train = list(range(max(0, first - horizon)))
    validation = list(range(first + horizon, second - horizon))
    # Tail labels have not matured in this supplied snapshot.
    test = list(range(second + horizon, n - horizon))
    if not train or not validation or not test:
        raise IntegrityViolation('样本不足以容纳训练、验证、测试及 purge/embargo')
    return dict(train=train, validation=validation, test=test, horizon_sessions=horizon,
                embargo_sessions=horizon, purged_sessions=2 * horizon,
                embargoed_sessions=2 * horizon, incomplete_tail_sessions=horizon,
                test_locked=True)


def check_fit_scope(split, *, fit_sessions, tune_sessions, attempts):
    if type(attempts) is not int or attempts < 1:
        raise IntegrityViolation('必须记录正整数尝试数')
    fit, tune = set(fit_sessions), set(tune_sessions)
    if (fit | tune) & set(split['test']):
        raise IntegrityViolation('测试段已锁定，不能拟合或反向调参')
    if not fit <= set(split['train']):
        raise IntegrityViolation('拟合只能使用训练段')
    if not tune <= set(split['validation']):
        raise IntegrityViolation('调参只能使用验证段')
    return dict(status='CHECKED', attempts=attempts, test_locked=True)


def assert_causal_prefix(frame, compute, *, checkpoints=None):
    dates = sorted(pd.unique(pd.to_datetime(frame.trade_date)))
    checkpoints = checkpoints or sorted(set([max(1, len(dates) // 2), max(1, len(dates) - 1)]))
    whole = compute(frame.copy(deep=True))
    for count in checkpoints:
        if not 0 < count < len(dates):
            continue
        mask = pd.to_datetime(frame.trade_date).le(dates[count - 1])
        subset = frame.loc[mask].copy(deep=True)
        actual = np.asarray(compute(subset), dtype=float)
        expected = np.asarray(whole, dtype=float)[mask.to_numpy()]
        if actual.shape != expected.shape or not np.allclose(actual, expected, rtol=1e-10, atol=1e-12, equal_nan=True):
            raise IntegrityViolation('前缀重算不一致：特征或信号可能依赖未来数据')
    return dict(status='PREFIX_CHECKED', checkpoints=list(checkpoints), proof=False)
