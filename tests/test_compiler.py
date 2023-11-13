import json
import re
import shutil
from pathlib import Path

import pytest
import solcx  # type: ignore
from ape import reverts
from ape.contracts import ContractContainer
from ape.exceptions import CompilerError
from ethpm_types.ast import ASTClassification
from packaging.version import Version
from pkg_resources import get_distribution
from requests.exceptions import ConnectionError

from ape_solidity import Extension
from ape_solidity._utils import OUTPUT_SELECTION
from ape_solidity.exceptions import IndexOutOfBoundsError

BASE_PATH = Path(__file__).parent / "contracts"
TEST_CONTRACT_PATHS = [
    p
    for p in BASE_PATH.iterdir()
    if ".cache" not in str(p) and not p.is_dir() and p.suffix == Extension.SOL.value
]
TEST_CONTRACTS = [str(p.stem) for p in TEST_CONTRACT_PATHS]
PATTERN_REQUIRING_COMMIT_HASH = re.compile(r"\d+\.\d+\.\d+\+commit\.[\d|a-f]+")
EXPECTED_NON_SOLIDITY_ERR_MSG = "Unable to compile 'RandomVyperFile.vy' using Solidity compiler."

# These are tested elsewhere, not in `test_compile`.
normal_test_skips = (
    "DifferentNameThanFile",
    "MultipleDefinitions",
    "RandomVyperFile",
    "LibraryFun",
    "JustAStruct",
)
raises_because_not_sol = pytest.raises(CompilerError, match=EXPECTED_NON_SOLIDITY_ERR_MSG)
DEFAULT_OPTIMIZER = {"enabled": True, "runs": 200}
APE_VERSION = Version(get_distribution("eth-ape").version.split(".dev")[0].strip())


@pytest.mark.parametrize(
    "contract",
    [c for c in TEST_CONTRACTS if all(n not in str(c) for n in normal_test_skips)],
)
def test_compile(project, contract):
    assert contract in project.contracts, ", ".join([n for n in project.contracts.keys()])
    contract = project.contracts[contract]
    assert contract.source_id == f"{contract.name}.sol"


def test_compile_solc_not_installed(project, fake_no_installs):
    assert len(project.load_contracts(use_cache=False)) > 0


def test_compile_when_offline(project, compiler, mocker):
    # When offline, getting solc versions raises a requests connection error.
    # This should trigger the plugin to return an empty list.
    patch = mocker.patch("ape_solidity.compiler.get_installable_solc_versions")
    patch.side_effect = ConnectionError

    # Using a non-specific contract - doesn't matter too much which one.
    source_path = project.contracts_folder / "MultipleDefinitions.sol"
    result = compiler.compile([source_path])
    assert len(result) > 0, "Nothing got compiled."


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


def test_compile_just_a_struct(compiler, project):
    """
    Before, you would get a nasty index error, even though this is valid Solidity.
    The fix involved using nicer access to "contracts" in the standard output JSON.
    """
    contract_types = compiler.compile([project.contracts_folder / "JustAStruct.sol"])
    assert len(contract_types) == 0


def test_get_imports(project, compiler):
    import_dict = compiler.get_imports(TEST_CONTRACT_PATHS, BASE_PATH)
    contract_imports = import_dict["Imports.sol"]
    # NOTE: make sure there aren't duplicates
    assert len([x for x in contract_imports if contract_imports.count(x) > 1]) == 0
    # NOTE: returning a list
    assert isinstance(contract_imports, list)
    # NOTE: in case order changes
    expected = {
        ".cache/BrownieDependency/local/BrownieContract.sol",
        ".cache/BrownieStyleDependency/local/BrownieStyleDependency.sol",
        ".cache/TestDependency/local/Dependency.sol",
        ".cache/gnosis/v1.3.0/common/Enum.sol",
        "CompilesOnce.sol",
        "MissingPragma.sol",
        "NumerousDefinitions.sol",
        "subfolder/Relativecontract.sol",
    }
    assert set(contract_imports) == expected


def test_get_imports_raises_when_non_solidity_files(compiler, vyper_source_path):
    with raises_because_not_sol:
        compiler.get_imports([vyper_source_path])


def test_get_import_remapping(compiler, project, config):
    import_remapping = compiler.get_import_remapping()
    assert import_remapping == {
        "@remapping_2_brownie": ".cache/BrownieDependency/local",
        "@dependency_remapping": ".cache/DependencyOfDependency/local",
        "@remapping_2": ".cache/TestDependency/local",
        "@remapping/contracts": ".cache/TestDependency/local",
        "@styleofbrownie": ".cache/BrownieStyleDependency/local",
        "@openzeppelin/contracts": ".cache/OpenZeppelin/v4.7.1",
        "@oz/contracts": ".cache/OpenZeppelin/v4.5.0",
        "@vault": ".cache/vault/v0.4.5",
        "@vaultmain": ".cache/vault/master",
        "@gnosis": ".cache/gnosis/v1.3.0",
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
        assert isinstance(project.BrownieContract, ContractContainer)

        # Ensure can access twice (to make sure caching does not break anything).
        _ = project.BrownieContract


def test_compile_single_source_with_no_imports(compiler, config):
    # Tests against an important edge case that was discovered
    # where the source file was individually compiled and it had no imports.
    path = Path(__file__).parent / "DependencyOfDependency"
    with config.using_project(path) as project:
        assert isinstance(project.DependencyOfDependency, ContractContainer)


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
    cache_folder = project.contracts_folder / ".cache"
    if cache_folder.is_dir():
        shutil.rmtree(cache_folder)

    file_paths = [
        project.contracts_folder / "ImportSourceWithEqualSignVersion.sol",
        project.contracts_folder / "SpecificVersionNoPrefix.sol",
        project.contracts_folder / "CompilesOnce.sol",
        project.contracts_folder / "Imports.sol",  # Uses mapped imports!
    ]
    version_map = compiler.get_version_map(file_paths)
    assert len(version_map) == 2

    expected_version = Version("0.8.12+commit.f00d7308")
    latest_version = [v for v in version_map if v != expected_version][0]
    assert all([f in version_map[expected_version] for f in file_paths[:-1]])

    latest_version_sources = version_map[latest_version]
    assert len(latest_version_sources) == 10, "Did the import remappings load correctly?"
    assert file_paths[-1] in latest_version_sources

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
        assert compiler.settings["optimizer"] == DEFAULT_OPTIMIZER
        assert compiler.settings["evmVersion"] == "constantinople"

    # No remappings for sources in the following compilers
    assert (
        "remappings" not in compiler_0812.settings
    ), f"Remappings found: {compiler_0812.settings['remappings']}"

    assert (
        "@openzeppelin/contracts=.cache/OpenZeppelin/v4.7.1"
        in compiler_latest.settings["remappings"]
    )
    assert "@vault=.cache/vault/v0.4.5" in compiler_latest.settings["remappings"]
    assert "@vaultmain=.cache/vault/master" in compiler_latest.settings["remappings"]
    common_suffix = ".cache/TestDependency/local"
    expected_remappings = (
        "@remapping_2_brownie=.cache/BrownieDependency/local",
        "@dependency_remapping=.cache/DependencyOfDependency/local",
        f"@remapping_2={common_suffix}",
        f"@remapping/contracts={common_suffix}",
        "@styleofbrownie=.cache/BrownieStyleDependency/local",
    )
    actual_remappings = compiler_latest.settings["remappings"]
    assert all(x in actual_remappings for x in expected_remappings)
    assert all(
        b >= a for a, b in zip(actual_remappings, actual_remappings[1:])
    ), "Import remappings should be sorted"
    assert f"@remapping/contracts={common_suffix}" in compiler_0426.settings["remappings"]
    assert "UseYearn" in compiler_latest.contractTypes
    assert "@gnosis=.cache/gnosis/v1.3.0" in compiler_latest.settings["remappings"]

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

    # The "latest" version will always be in this list, but avoid
    # asserting on it directly to handle new "latest"'s coming out.
    expected = ("0.4.26", "0.5.16", "0.6.12", "0.8.12", "0.8.14")
    assert all([e in versions for e in expected])


def test_get_compiler_settings(compiler, project):
    source_a = "ImportSourceWithEqualSignVersion.sol"
    source_b = "SpecificVersionNoPrefix.sol"
    source_c = "CompilesOnce.sol"
    source_d = "Imports.sol"  # Uses mapped imports!
    indirect_source = "SpecificVersionWithEqualSign.sol"
    file_paths = [project.contracts_folder / x for x in (source_a, source_b, source_c, source_d)]
    actual = compiler.get_compiler_settings(file_paths)
    v812 = Version("0.8.12+commit.f00d7308")
    latest = max(list(actual.keys()))
    expected_remappings = (
        "@remapping_2_brownie=.cache/BrownieDependency/local",
        "@dependency_remapping=.cache/DependencyOfDependency/local",
        "@remapping_2=.cache/TestDependency/local",
        "@remapping/contracts=.cache/TestDependency/local",
        "@styleofbrownie=.cache/BrownieStyleDependency/local",
        "@gnosis=.cache/gnosis/v1.3.0",
    )
    expected_v812_contracts = (source_a, source_b, source_c, indirect_source)
    expected_latest_contracts = (
        ".cache/BrownieDependency/local/BrownieContract.sol",
        "CompilesOnce.sol",
        ".cache/TestDependency/local/Dependency.sol",
        ".cache/DependencyOfDependency/local/DependencyOfDependency.sol",
        source_d,
        "subfolder/Relativecontract.sol",
        ".cache/gnosis/v1.3.0/common/Enum.sol",
    )

    # Shared compiler defaults tests
    expected_source_lists = (expected_v812_contracts, expected_latest_contracts)
    for version, expected_sources in zip((v812, latest), expected_source_lists):
        output_selection = actual[version]["outputSelection"]
        assert actual[version]["optimizer"] == DEFAULT_OPTIMIZER
        for _, item_selection in output_selection.items():
            for key, selection in item_selection.items():
                if key == "*":  # All contracts
                    assert selection == OUTPUT_SELECTION
                elif key == "":  # All sources
                    assert selection == ["ast"]

        actual_sources = [x for x in output_selection.keys()]
        for expected_source_id in expected_sources:
            assert (
                expected_source_id in actual_sources
            ), f"{expected_source_id} not one of {', '.join(actual_sources)}"

    # Remappings test
    actual_remappings = actual[latest]["remappings"]
    assert isinstance(actual_remappings, list)
    assert len(actual_remappings) == len(expected_remappings)
    assert all(e in actual_remappings for e in expected_remappings)
    assert all(
        b >= a for a, b in zip(actual_remappings, actual_remappings[1:])
    ), "Import remappings should be sorted"

    # Tests against bug potentially preventing JSON decoding errors related
    # to contract verification.
    for key, output_json_dict in actual.items():
        assert json.dumps(output_json_dict)


def test_evm_version(compiler):
    assert compiler.config.evm_version == "constantinople"


def test_source_map(project, compiler):
    source_path = project.contracts_folder / "MultipleDefinitions.sol"
    result = compiler.compile([source_path])[-1]
    assert result.sourcemap.__root__ == "124:87:0:-:0;;;;;;;;;;;;;;;;;;;"


def test_add_library(project, account, compiler, connection):
    with pytest.raises(AttributeError):
        # Does not exist yet because library is not deployed or known.
        _ = project.C

    library = project.Set.deploy(sender=account)
    compiler.add_library(library)

    # After deploying and adding the library, we can use contracts that need it.
    assert project.C


def test_enrich_error_when_custom(compiler, project, owner, not_owner, connection):
    compiler.compile((project.contracts_folder / "HasError.sol",))

    # Deploy so Ape know about contract type.
    contract = owner.deploy(project.HasError, 1)
    with pytest.raises(contract.Unauthorized) as err:
        contract.withdraw(sender=not_owner)

    # TODO: Can remove hasattr check after race condition resolved in Core.
    if hasattr(err.value, "inputs"):
        assert err.value.inputs == {"addr": not_owner.address, "counter": 123}


def test_enrich_error_when_custom_in_constructor(compiler, project, owner, not_owner, connection):
    # Deploy so Ape know about contract type.
    with reverts(project.HasError.Unauthorized) as err:
        not_owner.deploy(project.HasError, 0)

    # TODO: After ape 0.6.14, try this again. It is working locally but there
    #  may be a race condition causing it to fail? I added a fix to core that
    #  may resolve but I am not sure.
    if hasattr(err.value, "inputs"):
        assert err.value.inputs == {"addr": not_owner.address, "counter": 123}


def test_enrich_error_when_builtin(project, owner, connection):
    contract = project.BuiltinErrorChecker.deploy(sender=owner)
    with pytest.raises(IndexOutOfBoundsError):
        contract.checkIndexOutOfBounds(sender=owner)


def test_ast(project, compiler):
    source_path = project.contracts_folder / "MultipleDefinitions.sol"
    actual = compiler.compile([source_path])[-1].ast
    fn_node = actual.children[1].children[0]
    assert actual.ast_type == "SourceUnit"
    assert fn_node.classification == ASTClassification.FUNCTION


def test_via_ir(project, compiler):
    source_path = project.contracts_folder / "StackTooDeep.sol"
    source_code = """
// SPDX-License-Identifier: MIT

pragma solidity >=0.8.0;

contract StackTooDeep {
    // This contract tests the scenario when we have a contract with
    // too many local variables and the stack is too deep.
    // The compiler will throw an error when trying to compile this contract.
    // To get around the error, we can compile the contract with the
    // --via-ir flag

    function foo(
        uint256 a,
        uint256 b,
        uint256 c,
        uint256 d,
        uint256 e,
        uint256 f,
        uint256 g,
        uint256 h,
        uint256 i,
        uint256 j,
        uint256 k,
        uint256 l,
        uint256 m,
        uint256 n,
        uint256 o,
        uint256 p
    ) public pure returns (uint256) {

        uint256 sum = 0;

        for (uint256 index = 0; index < 16; index++) {
            uint256 innerSum = a + b + c + d + e + f + g + h + i + j + k + l + m + n + o + p;
            sum += innerSum;
        }

        return (sum);
    }

}
    """

    # write source code to file
    source_path.write_text(source_code)

    try:
        compiler.compile([source_path])
    except Exception as e:
        assert "Stack too deep" in str(e)

    compiler.config.via_ir = True

    compiler.compile([source_path])

    # delete source code file
    source_path.unlink()

    # flip the via_ir flag back to False
    compiler.config.via_ir = False


def test_flatten(project, compiler, data_folder):
    source_path = project.contracts_folder / "Imports.sol"
    with pytest.raises(CompilerError):
        compiler.flatten_contract(source_path)

    source_path = project.contracts_folder / "ImportingLessConstrainedVersion.sol"
    flattened_source = compiler.flatten_contract(source_path)
    flattened_source_path = data_folder / "ImportingLessConstrainedVersionFlat.sol"
    assert str(flattened_source) == str(flattened_source_path.read_text())


def test_compile_code(compiler):
    code = """
contract Contract {
    function snakes() pure public returns(bool) {
        return true;
    }
}
"""
    actual = compiler.compile_code(code, contractName="TestContractName")
    assert actual.name == "TestContractName"
    assert len(actual.abi) > 0
    assert actual.ast is not None
    assert len(actual.runtime_bytecode.bytecode) > 0
    assert len(actual.deployment_bytecode.bytecode) > 0
