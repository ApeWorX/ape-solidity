from enum import IntEnum
from typing import Union

from ape.exceptions import CompilerError, ConfigError, ContractLogicError
from ape.logging import LogLevel, logger
from solcx.exceptions import SolcError


class SolcInstallError(CompilerError):
    """
    Raised when `solc` is not installed
    and unable to be installed.
    """

    def __init__(self):
        super().__init__(
            "No versions of `solc` installed and unable to install latest `solc` version."
        )


class SolcCompileError(CompilerError):
    """
    Specifically, only errors arising from ``solc`` compile methods.
    This error is a modified version of ``SolcError`` to take into
    account Ape's logging verbosity.
    """

    def __init__(self, solc_error: SolcError):
        self.solc_error = solc_error

    def __str__(self) -> str:
        if logger.level <= LogLevel.DEBUG:
            # Show everything when in DEBUG mode.
            return str(self.solc_error)

        else:
            # Only show the error and line-number(s) where it occurred.
            return self.solc_error.message


class IncorrectMappingFormatError(ConfigError, ValueError):
    def __init__(self):
        super().__init__(
            "Incorrectly formatted 'solidity.remapping' config property. "
            "Expected '@value_1=value2'."
        )


class RuntimeErrorType(IntEnum):
    ASSERTION_ERROR = 0x1
    ARITHMETIC_UNDER_OR_OVERFLOW = 0x11
    DIVISION_BY_ZERO_ERROR = 0x12
    ENUM_CONVERSION_OUT_OF_BOUNDS = 0x21
    INCORRECTLY_ENCODED_STORAGE_BYTE_ARRAY = 0x22
    POP_ON_EMPTY_ARRAY = 0x31
    INDEX_OUT_OF_BOUNDS_ERROR = 0x32
    MEMORY_OVERFLOW_ERROR = 0x41
    ZERO_INITIALIZED_VARIABLE = 0x51


class SolidityRuntimeError(ContractLogicError):
    def __init__(self, error_type: RuntimeErrorType, message: str, **kwargs):
        self.error_type = error_type
        super().__init__(message, **kwargs)


class SolidityArithmeticError(SolidityRuntimeError, ArithmeticError):
    """
    Raised from math operations going wrong.
    """

    def __init__(self, **kwargs):
        message = "Arithmetic operation underflowed or overflowed outside of an unchecked block."
        super().__init__(RuntimeErrorType.ARITHMETIC_UNDER_OR_OVERFLOW, message, **kwargs)


class SolidityAssertionError(SolidityRuntimeError, AssertionError):
    """
    Raised from Solidity ``assert`` statements.
    You typically should never see this error, as higher-level Contract Logic error
    handled in the framework should appear first (with the correct revert message).
    """

    def __init__(self, **kwargs):
        message = "Assertion error."
        super().__init__(RuntimeErrorType.ASSERTION_ERROR, message, **kwargs)


class DivisionByZeroError(SolidityRuntimeError, ZeroDivisionError):
    """
    Raised when dividing goes wrong (such as using a 0 denominator).
    """

    def __init__(self, **kwargs):
        message = "Division or modulo division by zero"
        super().__init__(RuntimeErrorType.DIVISION_BY_ZERO_ERROR, message, **kwargs)


class EnumConversionError(SolidityRuntimeError):
    """
    Raised when Solidity fails to convert an enum value to its primitive type.
    """

    def __init__(self, **kwargs):
        message = "Tried to convert a value into an enum, but the value was too big or negative."
        super().__init__(RuntimeErrorType.ENUM_CONVERSION_OUT_OF_BOUNDS, message, **kwargs)


class EncodeStorageError(SolidityRuntimeError):
    """
    Raised when Solidity fails to encode a storage value.
    """

    def __init__(self, **kwargs):
        message = "Incorrectly encoded storage byte array."
        super().__init__(RuntimeErrorType.INCORRECTLY_ENCODED_STORAGE_BYTE_ARRAY, message, **kwargs)


class IndexOutOfBoundsError(SolidityRuntimeError, IndexError):
    """
    Raised when accessing an index that is out of bounds in your contract.
    """

    def __init__(self, **kwargs):
        message = "Array accessed at an out-of-bounds or negative index."
        super().__init__(RuntimeErrorType.INDEX_OUT_OF_BOUNDS_ERROR, message, **kwargs)


class MemoryOverflowError(SolidityRuntimeError, OverflowError):
    """
    Raised when exceeding the allocating memory for a data type
    in Solidity.
    """

    def __init__(self, **kwargs):
        message = "Too much memory was allocated, or an array was created that is too large."
        super().__init__(RuntimeErrorType.MEMORY_OVERFLOW_ERROR, message, **kwargs)


class PopOnEmptyArrayError(SolidityRuntimeError):
    """
    Raised when popping from a data-structure fails in your contract.
    """

    def __init__(self, **kwargs):
        message = ".pop() was called on an empty array."
        super().__init__(RuntimeErrorType.POP_ON_EMPTY_ARRAY, message, **kwargs)


class ZeroInitializedVariableError(SolidityRuntimeError):
    """
    Raised when calling a zero-initialized variable of internal function type.
    """

    def __init__(self, **kwargs):
        message = "Called a zero-initialized variable of internal function type."
        super().__init__(RuntimeErrorType.ZERO_INITIALIZED_VARIABLE, message, **kwargs)


RUNTIME_ERROR_CODE_PREFIX = "0x4e487b71"
RuntimeErrorUnion = Union[
    SolidityArithmeticError,
    SolidityAssertionError,
    DivisionByZeroError,
    EnumConversionError,
    EncodeStorageError,
    IndexOutOfBoundsError,
    MemoryOverflowError,
    PopOnEmptyArrayError,
    ZeroInitializedVariableError,
]
RUNTIME_ERROR_MAP: dict[RuntimeErrorType, type[RuntimeErrorUnion]] = {
    RuntimeErrorType.ASSERTION_ERROR: SolidityAssertionError,
    RuntimeErrorType.ARITHMETIC_UNDER_OR_OVERFLOW: SolidityArithmeticError,
    RuntimeErrorType.DIVISION_BY_ZERO_ERROR: DivisionByZeroError,
    RuntimeErrorType.ENUM_CONVERSION_OUT_OF_BOUNDS: EnumConversionError,
    RuntimeErrorType.INCORRECTLY_ENCODED_STORAGE_BYTE_ARRAY: EncodeStorageError,
    RuntimeErrorType.INDEX_OUT_OF_BOUNDS_ERROR: IndexOutOfBoundsError,
    RuntimeErrorType.MEMORY_OVERFLOW_ERROR: MemoryOverflowError,
    RuntimeErrorType.POP_ON_EMPTY_ARRAY: PopOnEmptyArrayError,
    RuntimeErrorType.ZERO_INITIALIZED_VARIABLE: ZeroInitializedVariableError,
}
