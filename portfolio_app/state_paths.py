"""Single local state root; no path is echoed to user-facing messages."""
import os
from pathlib import Path


def state_root():
    configured = os.environ.get('PORTFOLIO_STATE_DIR')
    return Path(configured).expanduser().resolve() if configured else Path(__file__).resolve().parents[1] / 'output'
