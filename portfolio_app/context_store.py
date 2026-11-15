"""Content-addressed local links for contexts too large for a browser URL."""
import hashlib
import json
import re

from .context_migration import load_context
from .research_context import ContractViolation
from .state_paths import state_root


def save_context(context):
    encoded = json.dumps(context.to_dict(), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    reference = 'link-' + hashlib.sha256(encoded.encode()).hexdigest()
    root = state_root() / 'context_links'
    root.mkdir(parents=True, exist_ok=True)
    # Identical content has the same name; exclusive creation avoids partial rewrites.
    target = root / (reference + '.json')
    if not target.exists():
        import os
        import tempfile
        descriptor, temporary = tempfile.mkstemp(dir=root, suffix='.tmp')
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(encoded)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return reference


def restore_context(reference):
    if not isinstance(reference, str) or not re.fullmatch(r'link-[0-9a-f]{64}', reference):
        raise ContractViolation('本机上下文引用无效')
    try:
        encoded = (state_root() / 'context_links' / (reference + '.json')).read_text(encoding='utf-8')
    except OSError as exc:
        raise ContractViolation('本机研究上下文不存在；请在原机器打开或重新选择研究范围') from exc
    if 'link-' + hashlib.sha256(encoded.encode()).hexdigest() != reference:
        raise ContractViolation('本机研究上下文内容校验失败')
    try:
        return load_context(json.loads(encoded))
    except (ValueError, TypeError) as exc:
        raise ContractViolation('本机研究上下文无法读取') from exc
