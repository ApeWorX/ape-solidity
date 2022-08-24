from ape.exceptions import ConfigError


class IncorrectMappingFormatError(ConfigError):
    def __init__(self):
        super().__init__(
            "Incorrectly formatted 'solidity.remapping' config property. "
            "Expected '@value_1=value2'."
        )
