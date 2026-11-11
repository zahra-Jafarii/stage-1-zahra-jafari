"""Dataset registry: the config key `dataset` picks one of these."""
from ..exceptions import ConfigError
from ..dataset import Dataset
from .nyc311 import NYC311

DATASETS = {NYC311.name: NYC311}


def get_dataset(name: str) -> Dataset:
    try:
        return DATASETS[name]
    except KeyError:
        raise ConfigError(f"unknown dataset {name!r}; known: {sorted(DATASETS)}") from None
