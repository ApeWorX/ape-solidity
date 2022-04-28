from pathlib import Path

import pytest

TEST_CONTRACTS = [
    str(p.stem) for p in (Path(__file__).parent / "contracts").iterdir() if ".cache" not in str(p)
]


@pytest.mark.parametrize("contract", TEST_CONTRACTS)
def test_integration(project, contract):
    assert contract in project.contracts
    contract = project.contracts[contract]
    assert contract.source_id == f"{contract.name}.sol"
