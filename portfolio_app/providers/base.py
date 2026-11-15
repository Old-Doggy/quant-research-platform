from dataclasses import dataclass
import pandas as pd


class ProviderError(ValueError):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderBatch:
    frame: pd.DataFrame
    raw: pd.DataFrame
    metadata: dict
    completeness: str
