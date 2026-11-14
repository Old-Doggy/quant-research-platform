"""Fail early when an incremental workspace bridge has an incomplete contract."""


def bind_workspace_dependencies(target, supplied, required):
    missing = set(required) - set(supplied)
    if missing:
        raise ValueError('workspace dependencies incomplete: ' + ', '.join(sorted(missing)))
    target.update({name: supplied[name] for name in required})
