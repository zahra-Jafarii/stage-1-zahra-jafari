"""What the pipeline needs to know about one dataset."""
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from .config import Config
from .contract import Contract


def nothing_to_prepare(config: Config) -> None:
    return None


def keep_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame


def no_enrichers(config: Config) -> list:
    return []


def no_references(config: Config) -> dict:
    return {}


@dataclass(frozen=True)
class Dataset:
    name: str
    build_contract: Callable[[Config], Contract]
    # runs before reading data (for example: build a reference file)
    prepare: Callable[[Config], None] = nothing_to_prepare
    # adds derived columns to a cleaned batch
    derive: Callable[[pd.DataFrame], pd.DataFrame] = keep_frame
    # reference joins applied to every cleaned batch
    build_enrichers: Callable[[Config], list] = no_enrichers
    # facts about reference sources for the manifest (link, date, hash)
    describe_references: Callable[[Config], dict] = no_references
    # extra output files built from cases.csv; gets (config, outputs) and returns new outputs
    build_extra_outputs: Optional[Callable[[Config, dict], dict]] = None
