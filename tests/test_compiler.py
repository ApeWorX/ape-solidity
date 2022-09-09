import re
from pathlib import Path

import pytest
import solcx  # type: ignore
from ape.contracts import ContractContainer
from ape.exceptions import CompilerError
from semantic_version import Version  # type: ignore

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACT_PATHS = [
    p
    for p in BASE_PATH.iterdir()
    if ".cache" not in str(p) and not p.is_dir() and p.suffix == ".sol"
]
TEST_CONTRACTS = [str(p.stem) for p in TEST_CONTRACT_PATHS]
PATTERN_REQUIRING_COMMIT_HASH = re.compile(r"\d+\.\d+\.\d+\+commit\.[\d|a-f]+")
EXPECTED_NON_SOLIDITY_ERR_MSG = "Unable to compile 'RandomVyperFile.vy' using Solidity compiler."

# These are tested elsewhere, not in `test_compile`.
normal_test_skips = ("DifferentNameThanFile", "MultipleDefinitions", "RandomVyperFile")
raises_because_not_sol = pytest.raises(CompilerError, match=EXPECTED_NON_SOLIDITY_ERR_MSG)


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


def test_compile_vyper_contract(compiler, vyper_source_path):
    with raises_because_not_sol:
        compiler.compile([vyper_source_path])


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


def test_get_imports_raises_when_non_solidity_files(compiler, vyper_source_path):
    with raises_because_not_sol:
        compiler.get_imports([vyper_source_path])


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
        actual_versions = ", ".join(str(v) for v in version_map)
        fail_msg = f"Actual versions: {actual_versions}"
        expected_version = Version("0.8.12+commit.f00d7308")
        assert expected_version in version_map, fail_msg
        assert version_map[expected_version] == {source_path}, fail_msg


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
    assert all([f in version_map[Version("0.8.12+commit.f00d7308")] for f in file_paths[:-1]])

    # Will fail if the import remappings have not loaded yet.
    assert all([f.is_file() for f in file_paths])


def test_get_version_map_single_source(compiler, project):
    # Source has no imports
    source = project.contracts_folder / "OlderVersion.sol"
    actual = compiler.get_version_map([source])
    expected = {Version("0.5.16+commit.9c3226ce"): {source}}
    assert len(actual) == 1
    assert actual == expected, f"Actual version: {[k for k in actual.keys()][0]}"


def test_get_version_map_raises_on_non_solidity_sources(compiler, vyper_source_path):
    with raises_because_not_sol:
        compiler.get_version_map([vyper_source_path])


def test_compiler_data_in_manifest(project):
    manifest = project.extract_manifest()
    compilers = [c for c in manifest.compilers if c.name == "solidity"]
    latest_version = max(c.version for c in compilers)

    compiler_latest = [c for c in compilers if str(c.version) == latest_version][0]
    compiler_0812 = [c for c in compilers if str(c.version) == "0.8.12+commit.f00d7308"][0]
    compiler_0612 = [c for c in compilers if str(c.version) == "0.6.12+commit.27d51765"][0]
    compiler_0426 = [c for c in compilers if str(c.version) == "0.4.26+commit.4563c3fc"][0]

    # Compiler name test
    for compiler in (compiler_latest, compiler_0812, compiler_0612, compiler_0426):
        assert compiler.name == "solidity"

    # Compiler settings test
    expected_optimizer = {"enabled": True, "runs": 200}
    assert compiler_latest.settings["optimizer"] == expected_optimizer
    assert compiler_0812.settings["optimizer"] == expected_optimizer
    assert compiler_0612.settings["optimizer"] == expected_optimizer
    assert compiler_0426.settings["optimizer"] == expected_optimizer

    # No remappings for sources in the following compilers
    assert "remappings" not in compiler_0812.settings
    assert "remappings" not in compiler_0612.settings

    common_suffix = ".cache/TestDependency/local"
    expected_remappings = {
        f"@remapping/contracts={common_suffix}",
        f"@remapping_2={common_suffix}",
        "@brownie=.cache/BrownieDependency/local",
        "@dependency_remapping=.cache/TestDependencyOfDependency/local",
    }
    assert compiler_latest.settings["remappings"] == expected_remappings
    # 0.4.26 should have absolute paths here due to lack of base_path
    assert (
        f"@remapping/contracts={project.contracts_folder}/{common_suffix}"
        in compiler_0426.settings["remappings"]
    )

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


def test_get_versions(compiler, project):
    # NOTE: the expected versions **DO NOT** contain commit hashes here
    # because we can only get the commit hash of installed compilers
    # and this returns all versions including uninstalled.
    versions = compiler.get_versions(project.source_paths)
    assert versions == {
        "0.8.14",
        "0.8.17",
        "0.6.12",
        "0.4.26",
        "0.5.16",
        "0.8.12",
    }
