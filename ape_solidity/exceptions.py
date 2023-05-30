from enum import Enum
from typing import Dict, Type, Union

from ape.exceptions import ConfigError, ContractLogicError


class IncorrectMappingFormatError(ConfigError, ValueError):
    def __init__(self):
        super().__init__(
            "Incorrectly formatted 'solidity.remapping' config property. "
            "Expected '@value_1=value2'."
        )


class RuntimeErrorType(Enum):
    ASSERTION_ERROR = "0x4e487b710000000000000000000000000000000000000000000000000000000000000001"
    ARITHMETIC_ERROR = "0x4e487b710000000000000000000000000000000000000000000000000000000000000011"
    DIVISION_ERROR = "0x4e487b710000000000000000000000000000000000000000000000000000000000000012"
    ENUM_CONVERSION_ERROR = (
        "0x4e487b710000000000000000000000000000000000000000000000000000000000000021"
    )
    ENCODE_STORAGE_ERROR = (
        "0x4e487b710000000000000000000000000000000000000000000000000000000000000022"
    )
    POP_ERROR = "0x4e487b710000000000000000000000000000000000000000000000000000000000000031"
    INDEX_OUT_OF_BOUNDS_ERROR = (
        "0x4e487b710000000000000000000000000000000000000000000000000000000000000032"
    )
    MEMORY_OVERFLOW_ERROR = (
        "0x4e487b710000000000000000000000000000000000000000000000000000000000000041"
    )
    ZERO_VAR_ERROR = "0x4e487b710000000000000000000000000000000000000000000000000000000000000051"


class SolidityRuntimeError(ContractLogicError):
    def __init__(self, error_type: RuntimeErrorType, message: str, **kwargs):
        self.error_type = error_type
        super().__init__(message, **kwargs)


class SolidityArithmeticError(SolidityRuntimeError, ArithmeticError):
    """
    Raised from math operations going wrong.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.ARITHMETIC_ERROR, **kwargs)


class SolidityAssertionError(SolidityRuntimeError, AssertionError):
    """
    Raised from Solidity ``assert`` statements.
    You typically should never see this error, as higher-level Contract Logic error
    handled in the framework should appear first (with the correct revert message).
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.ASSERTION_ERROR, **kwargs)


class DivisionError(SolidityRuntimeError):
    """
    Raised when dividing goes wrong (such as using a 0 denominator).
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.DIVISION_ERROR, **kwargs)


class EnumConversionError(SolidityRuntimeError):
    """
    Raised when Solidity fails to convert an enum value to its primitive type.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.ENUM_CONVERSION_ERROR, **kwargs)


class EncodeStorageError(SolidityRuntimeError):
    """
    Raised when Solidity fails to encode a storage value.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.ENCODE_STORAGE_ERROR, **kwargs)


class IndexOutOfBoundsError(SolidityRuntimeError, IndexError):
    """
    Raised when accessing an index that is out of bounds in your contract.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.INDEX_OUT_OF_BOUNDS_ERROR, **kwargs)


class MemoryOverflowError(SolidityRuntimeError, OverflowError):
    """
    Raised when exceeding the allocating memory for a data type
    in Solidity.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.MEMORY_OVERFLOW_ERROR, **kwargs)


class PopError(SolidityRuntimeError):
    """
    Raised when popping from a data-structure fails in your contract.
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.POP_ERROR, **kwargs)


class ZeroVarError(SolidityRuntimeError):
    """
    TODO (wtf is this)
    """

    def __init__(self, **kwargs):
        super().__init__(RuntimeErrorType.ZERO_VAR_ERROR, **kwargs)


RuntimeErrorUnion = Union[
    SolidityArithmeticError,
    SolidityAssertionError,
    DivisionError,
    EnumConversionError,
    EncodeStorageError,
    IndexOutOfBoundsError,
    MemoryOverflowError,
    PopError,
    ZeroVarError,
]
RUNTIME_ERROR_MAP: Dict[RuntimeErrorType, Type[RuntimeErrorUnion]] = {
    RuntimeErrorType.ASSERTION_ERROR: SolidityAssertionError,
    RuntimeErrorType.ARITHMETIC_ERROR: SolidityArithmeticError,
    RuntimeErrorType.DIVISION_ERROR: DivisionError,
    RuntimeErrorType.ENUM_CONVERSION_ERROR: EnumConversionError,
    RuntimeErrorType.ENCODE_STORAGE_ERROR: EncodeStorageError,
    RuntimeErrorType.INDEX_OUT_OF_BOUNDS_ERROR: IndexOutOfBoundsError,
    RuntimeErrorType.MEMORY_OVERFLOW_ERROR: MemoryOverflowError,
    RuntimeErrorType.POP_ERROR: PopError,
    RuntimeErrorType.ZERO_VAR_ERROR: ZeroVarError,
}
