"""Project exceptions; each one maps to its own process exit code."""


class FactoryError(Exception):
    exit_code = 1


class ConfigError(FactoryError):
    exit_code = 2


class NetworkError(FactoryError):
    exit_code = 3


class InvalidResponseError(NetworkError):
    """HTTP 200 but the body is not usable."""


class DataValidationError(FactoryError):
    exit_code = 4


class SchemaDriftError(DataValidationError):
    exit_code = 5


class QuarantineThresholdError(DataValidationError):
    exit_code = 6


class DestinationError(FactoryError):
    """Writing to a destination (for example the database) failed."""
    exit_code = 7
