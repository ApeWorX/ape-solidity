from pathlib import Path

TEST_PROJECTS = [str(p.stem) for p in (Path(__file__).parent / "contracts").iterdir()]


def test_integration(project):
    for proj in TEST_PROJECTS:
        assert proj in project.contracts
        contract = project.contracts[proj]
        assert f"contracts/{proj}.sol" in contract.sourceId
