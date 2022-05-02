from pathlib import Path

import pytest

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACTS = [str(p.stem) for p in BASE_PATH.iterdir() if ".cache" not in str(p)]


@pytest.mark.parametrize(
    "contract", [c for c in TEST_CONTRACTS if "DifferentNameThanFile" not in str(c)]
)
def test_integration(project, contract):
    assert contract in project.contracts
    contract = project.contracts[contract]
    assert contract.source_id == f"{contract.name}.sol"


def test_compile_contract_with_different_name_than_file(project):
    file_name = "DifferentNameThanFile.sol"
    contract = project.contracts["ApeDifferentNameThanFile"]
    assert contract.source_id == file_name
