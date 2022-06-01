import pytest
from ape._cli import cli
from click.testing import CliRunner


@pytest.fixture
def ape_cli():
    return cli


@pytest.fixture
def runner():
    return CliRunner()


def test_compile_using_cli(ape_cli, runner):
    result = runner.invoke(ape_cli, ["compile"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "CompilesOnce" in result.output
    result = runner.invoke(ape_cli, ["compile"], catch_exceptions=False)

    # Already compiled so does not compile again.
    assert "CompilesOnce" not in result.output


@pytest.mark.parametrize(
    "contract_path",
    ("CompilesOnce", "CompilesOnce.sol", "contracts/CompilesOnce", "contracts/CompilesOnce.sol"),
)
def test_compile_specified_contracts(ape_cli, runner, contract_path):
    result = runner.invoke(ape_cli, ["compile", contract_path, "--force"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "Compiling 'CompilesOnce.sol'" in result.output
