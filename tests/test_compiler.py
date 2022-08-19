from pathlib import Path

import pytest
import solcx  # type: ignore
from ape.contracts import ContractContainer
from semantic_version import Version  # type: ignore

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACT_PATHS = [p for p in BASE_PATH.iterdir() if ".cache" not in str(p) and not p.is_dir()]
TEST_CONTRACTS = [str(p.stem) for p in TEST_CONTRACT_PATHS]

# These are tested elsewhere, not in `test_compile`.
normal_test_skips = ("DifferentNameThanFile", "MultipleDefinitions")


@pytest.mark.parametrize(
    "contract", [c for c in TEST_CONTRACTS if all(n not in str(c) for n in normal_test_skips)]
)
def test_compile(project, contract):
    assert contract in project.contracts, ", ".join([n for n in project.contracts.keys()])
    contract = project.contracts[contract]
    assert contract.source_id == f"{contract.name}.sol"


def test_compile_multiple_definitions_in_source(project, compiler):
    source_path = project.contracts_folder / "MultipleDefinitions.sol"
    result = compiler.compile([source_path])
    assert len(result) == 2
    assert [r.name for r in result] == ["IMultipleDefinitions", "MultipleDefinitions"]
    assert all(r.source_id == "MultipleDefinitions.sol" for r in result)

    assert project.MultipleDefinitions
    assert project.IMultipleDefinitions


def test_compile_specific_order(project, compiler):
    # NOTE: This test seems random but it's important!
    # It replicates a bug where the first contract had a low solidity version
    # and the second had a bunch of imports.
    ordered_files = [
        project.contracts_folder / "OlderVersion.sol",
        project.contracts_folder / "Imports.sol",
    ]
    compiler.compile(ordered_files)


def test_compile_missing_version(project, compiler, temp_solcx_path):
    """
    Test the compilation of a contract with no defined pragma spec.

    The plugin should implicitly download the latest version to compile the
    contract with. `temp_solcx_path` is used to simulate an environment without
    compilers installed.
    """
    assert not solcx.get_installed_solc_versions()

    contract_types = compiler.compile([project.contracts_folder / "MissingPragma.sol"])

    assert len(contract_types) == 1

    installed_versions = solcx.get_installed_solc_versions()

    assert len(installed_versions) == 1
    assert installed_versions[0] == max(solcx.get_installable_solc_versions())


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


def test_version_specified_in_config_file(compiler, config):
    path = Path(__file__).parent / "VersionSpecifiedInConfig"
    with config.using_project(path) as project:
        source_path = project.contracts_folder / "VersionSpecifiedInConfig.sol"
        version_map = compiler.get_version_map(source_path)
        assert version_map[Version("0.8.12")] == {source_path}


def test_get_version_map(project, compiler):
    # Files are selected in order to trigger `CompilesOnce.sol` to
    # get removed from version '0.8.12'.
    file_paths = [
        project.contracts_folder / "ImportSourceWithEqualSignVersion.sol",
        project.contracts_folder / "SpecificVersionNoPrefix.sol",
        project.contracts_folder / "CompilesOnce.sol",
        project.contracts_folder / "Imports.sol",  # Uses mapped imports!
    ]
    version_map = compiler.get_version_map(file_paths)
    assert len(version_map) == 2
    assert all([f in version_map[Version("0.8.12")] for f in file_paths[:-1]])

    # Will fail if the import remappings have not loaded yet.
    assert all([f.is_file() for f in file_paths])


def test_compiler_data_in_manifest(project):
    manifest = project.extract_manifest()

    compiler_0812 = [c for c in manifest.compilers if str(c.version) == "0.8.12"][0]
    compiler_0612 = [c for c in manifest.compilers if str(c.version) == "0.6.12"][0]
    compiler_0426 = [c for c in manifest.compilers if str(c.version) == "0.4.26"][0]

    # Compiler name test
    assert compiler_0812.name == "solidity"
    assert compiler_0612.name == "solidity"
    assert compiler_0426.name == "solidity"

    # Compiler settings test
    assert compiler_0812.settings["optimize"] is True
    assert compiler_0612.settings["optimize"] is True
    assert compiler_0426.settings["optimize"] is True

    # Output values test
    output_values = [
        "abi",
        "bin",
        "bin-runtime",
        "devdoc",
        "userdoc",
    ]
    assert compiler_0812.settings["output_values"] == output_values
    assert compiler_0612.settings["output_values"] == output_values
    assert compiler_0426.settings["output_values"] == output_values

    # Import remappings test
    remappings = {
        "@remapping/contracts": ".cache/TestDependency/local",
        "@remapping_2": ".cache/TestDependency/local",
        "@brownie": ".cache/BrownieDependency/local",
        "@dependency_remapping": ".cache/TestDependencyOfDependency/local",
    }
    assert compiler_0812.settings["import_remappings"] == remappings
    assert compiler_0612.settings["import_remappings"] == remappings
    # 0426 should have absolute paths here due to lack of base_path
    absolute_remappings = {
        prefix: str(project.contracts_folder / path) for prefix, path in remappings.items()
    }
    assert compiler_0426.settings["import_remappings"] == absolute_remappings

    # Base path test
    assert compiler_0812.settings["base_path"]
    assert compiler_0612.settings["base_path"]
    # 0426 does not have base path
    assert "base_path" not in compiler_0426.settings

    # Compiler contract types test
    assert set(compiler_0812.contractTypes) == {
        "ImportSourceWithEqualSignVersion",
        "ImportSourceWithNoPrefixVersion",
        "ImportingLessConstrainedVersion",
        "IndirectlyImportingMoreConstrainedVersion",
        "IndirectlyImportingMoreConstrainedVersionCompanion",
        "SpecificVersionNoPrefix",
        "SpecificVersionRange",
        "SpecificVersionWithEqualSign",
        "CompilesOnce",
        "IndirectlyImportingMoreConstrainedVersionCompanionImport",
    }
    assert set(compiler_0612.contractTypes) == {"RangedVersion", "VagueVersion"}
    assert set(compiler_0426.contractTypes) == {
        "ExperimentalABIEncoderV2",
        "SpacesInPragma",
        "ImportOlderDependency",
    }
