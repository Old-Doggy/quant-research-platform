"""Read old contexts without inventing snapshot or price provenance."""
from dataclasses import fields
from collections.abc import Mapping

from .research_context import ContractViolation, ResearchContext


def load_context(payload: Mapping) -> ResearchContext:
    if not isinstance(payload, Mapping):
        raise ContractViolation('context must be a mapping')
    allowed = {field.name for field in fields(ResearchContext) if field.init}
    unknown = set(payload) - allowed - {'context_id'}
    if unknown:
        raise ContractViolation('unknown context field: ' + ', '.join(sorted(unknown)))
    values = {key: value for key, value in payload.items() if key in allowed}
    # Absence of a schema identifies the original serialized contract.
    values.setdefault('schema_version', '1.0')
    missing = [name for name in ('dataset_id', 'workspace', 'as_of') if name not in values]
    if missing:
        raise ContractViolation('context is missing: ' + ', '.join(missing))
    context = ResearchContext(**values)
    if payload.get('context_id') and context.context_id != payload['context_id']:
        raise ContractViolation('context_id does not match the context fields')
    return context


def upgrade_context(payload: Mapping, **provenance) -> ResearchContext:
    old = load_context(payload)
    required = ('snapshot_id', 'dataset_generation', 'price_basis', 'return_definition')
    missing = [name for name in required if provenance.get(name, getattr(old, name)) is None]
    if missing:
        raise ContractViolation('context upgrade requires: ' + ', '.join(missing))
    values = old.to_dict()
    values.pop('context_id')
    values.update(provenance, schema_version='2.0')
    return load_context(values)
