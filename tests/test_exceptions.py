import pytest
from ape.logging import logger
from solcx.exceptions import SolcError

from ape_solidity.exceptions import SolcCompileError

MESSAGE = "__message__"
COMMAND = ["solc", "command"]
RETURN_CODE = 123
STDOUT_DATA = "<stdout data>"
STDERR_DATA = "<stderr data>"


@pytest.fixture(scope="module")
def solc_error():
    return SolcError(
        message=MESSAGE,
        command=COMMAND,
        return_code=RETURN_CODE,
        stdout_data=STDOUT_DATA,
        stderr_data=STDERR_DATA,
    )


def test_solc_compile_error(solc_error):
    error = SolcCompileError(solc_error)
    actual = str(error)
    assert MESSAGE in actual
    assert f"{RETURN_CODE}" not in actual
    assert " ".join(COMMAND) not in actual
    assert STDOUT_DATA not in actual
    assert STDERR_DATA not in actual


def test_solc_compile_error_verbose(solc_error):
    logger.set_level("DEBUG")
    error = SolcCompileError(solc_error)
    actual = str(error)
    assert MESSAGE in actual
    assert f"{RETURN_CODE}" in actual
    assert " ".join(COMMAND) in actual
    assert STDOUT_DATA in actual
    assert STDERR_DATA in actual
    logger.set_level("INFO")
