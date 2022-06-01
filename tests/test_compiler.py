from pathlib import Path

import pytest
from ape.contracts import ContractContainer
from semantic_version import Version  # type: ignore

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACT_PATHS = [p for p in BASE_PATH.iterdir() if ".cache" not in str(p) and not p.is_dir()]
TEST_CONTRACTS = [str(p.stem) for p in TEST_CONTRACT_PATHS]


@pytest.mark.parametrize(
    "contract", [c for c in TEST_CONTRACTS if "DifferentNameThanFile" not in str(c)]
)
def test_compile(project, contract):
    assert contract in project.contracts, ", ".join([n for n in project.contracts.keys()])
    contract = project.contracts[contract]
    assert contract.source_id == f"{contract.name}.sol"


def test_compile_specific_order(project, compiler):
    # NOTE: This test seems random but it's important!
    # It replicates a bug where the first contract had a low solidity version
    # and the second had a bunch of imports.
    ordered_files = [
        project.contracts_folder / "OlderVersion.sol",
        project.contracts_folder / "Imports.sol",
    ]
    compiler.compile(ordered_files)


def test_compile_contract_with_different_name_than_file(project):
    file_name = "DifferentNameThanFile.sol"
    contract = project.contracts["ApeDifferentNameThanFile"]
    assert contract.source_id == file_name


def test_compile_only_returns_contract_types_for_inputs(compiler, project):
    # The compiler has to compile multiple files for 'Imports.sol' (it imports stuff).
    # However - it should only return a single contract type in this case.
    contract_types = compiler.compile([project.contracts_folder / "Imports.sol"])
    assert len(contract_types) == 1
    assert contract_types[0].name == "Imports"


def test_get_imports(project, compiler):
    import_dict = compiler.get_imports(TEST_CONTRACT_PATHS, BASE_PATH)
    contract_imports = import_dict["Imports.sol"]
    # NOTE: make sure there aren't duplicates
    assert len([x for x in contract_imports if contract_imports.count(x) > 1]) == 0
    # NOTE: returning a list
    assert type(contract_imports) == list
    # NOTE: in case order changes
    expected = {
        "CompilesOnce.sol",
        ".cache/TestDependency/local/Dependency.sol",
        "subfolder/Relativecontract.sol",
        ".cache/BrownieDependency/local/BrownieContract.sol",
    }
    assert set(contract_imports) == expected


def test_get_import_remapping(compiler, project, config):
    import_remapping = compiler.get_import_remapping()
    assert import_remapping == {
        "@remapping/contracts": ".cache/TestDependency/local",
        "@remapping_2": ".cache/TestDependency/local",
        "@brownie": ".cache/BrownieDependency/local",
        "@dependency_remapping": ".cache/TestDependencyOfDependency/local",
    }

    with config.using_project(project.path / "ProjectWithinProject") as proj:
        # Trigger downloading dependencies in new ProjectWithinProject
        dependencies = proj.dependencies
        assert dependencies
        # Should be different now that we have changed projects.
        second_import_remapping = compiler.get_import_remapping()
        assert second_import_remapping

    assert import_remapping != second_import_remapping


def test_brownie_project(compiler, config):
    brownie_project_path = Path(__file__).parent / "BrownieProject"
    with config.using_project(brownie_project_path) as project:
        assert type(project.BrownieContract) == ContractContainer


def test_compile_single_source_with_no_imports(compiler, config):
    # Tests against an important edge case that was discovered
    # where the source file was individually compiled and it had no imports.
    path = Path(__file__).parent / "DependencyOfDependency"
    with config.using_project(path) as project:
        assert type(project.DependencyOfDependency) == ContractContainer


def test_get_version_map(project, compiler):
    # Files are selected in order to trigger `CompilesOnce.sol` to
    # get removed from version '0.8.12'.
    file_paths = [
        project.contracts_folder / "ImportSourceWithEqualSignVersion.sol",
        project.contracts_folder / "SpecificVersionNoPrefix.sol",
        project.contracts_folder / "CompilesOnce.sol",
    ]
    version_map = compiler.get_version_map(file_paths)
    expected_version = Version("0.8.12")
    assert len(version_map) == 1
    assert expected_version in version_map
    assert all([f in version_map[expected_version] for f in file_paths])
