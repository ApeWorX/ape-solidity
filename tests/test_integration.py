from pathlib import Path

TEST_CONTRACTS = [
    str(p.stem) for p in (Path(__file__).parent / "contracts").iterdir() if ".cache" not in str(p)
]


def test_integration(project):
    for contract in TEST_CONTRACTS:
        assert contract in project.contracts
        contract = project.contracts[contract]
        assert contract.source_id == f"{contract.name}.sol"
