from pathlib import Path

import pytest

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACT_PATHS = [p for p in BASE_PATH.iterdir() if ".cache" not in str(p) and not p.is_dir()]
TEST_CONTRACTS = [str(p.stem) for p in TEST_CONTRACT_PATHS]
EXPECTED_IMPORTS_SET = {
    "folder/Relativecontract.sol",
    "CompilesOnce.sol",
    ".cache/__test_dependency__/local/Dependency.sol",
}


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


def test_get_imports(project, compiler):
    import_dict = compiler.get_imports(TEST_CONTRACT_PATHS, BASE_PATH)
    contract_imports = import_dict["Imports.sol"]
    # NOTE: make sure there aren't duplicates
    assert len([x for x in contract_imports if contract_imports.count(x) > 1]) == 0
    # NOTE: returning a list
    assert type(contract_imports) == list
    # NOTE: in case order changes
    assert EXPECTED_IMPORTS_SET == set(contract_imports)


def test_get_import_remapping(compiler, project, config):
    import_remapping = compiler.get_import_remapping()
    assert import_remapping

    with config.using_project(project.path / "project") as proj:
        # Trigger downloading dependencies in new project
        dependencies = proj.dependencies
        assert dependencies
        # Should be different now that we have changed projects.
        second_import_remapping = compiler.get_import_remapping()
        assert second_import_remapping

    assert import_remapping != second_import_remapping
