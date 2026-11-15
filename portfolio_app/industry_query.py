"""Resolve one historical industry classification without current-sector backfill."""


def industry_at(store,identifier, *, symbols, session, master):
    payload=store.open(identifier)
    assignments={}
    for group in payload['coverage']['groups']:
        result=store.members(identifier,group=group,session=session,master=master)
        for symbol in set(result['symbols'])&set(symbols):
            if symbol in assignments:
                raise ValueError('同一分类版本同日证券对应多个行业，需核对区间')
            assignments[symbol]=group
    missing=sorted(set(symbols)-set(assignments))
    return dict(status='partial' if missing else 'complete',assignments=assignments,missing_symbols=missing,
        session=session,membership_id=identifier,classification_version=payload['classification_version'])
