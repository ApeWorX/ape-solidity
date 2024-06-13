from pathlib import Path

import pytest
import solcx
from ape import Project, reverts
from ape.exceptions import CompilerError
from ape.utils import get_full_extension
from ethpm_types import ContractType
from packaging.version import Version

from ape_solidity.exceptions import IndexOutOfBoundsError

EXPECTED_NON_SOLIDITY_ERR_MSG = "Unable to compile 'RandomVyperFile.vy' using Solidity compiler."
raises_because_not_sol = pytest.raises(CompilerError, match=EXPECTED_NON_SOLIDITY_ERR_MSG)


def test_get_config(project, compiler):
    actual = compiler.get_config(project=project)
    assert actual.evm_version == "constantinople"


def test_get_import_remapping(project, compiler):
    actual = compiler.get_import_remapping(project=project)
    expected = {
        "@browniedependency": "contracts/.cache/browniedependency/local",
        "@dependency": "contracts/.cache/dependency/local",
        "@dependencyofdependency": "contracts/.cache/dependencyofdependency/local",
        "@noncompilingdependency": "contracts/.cache/noncompilingdependency/local",
        "@openzeppelin": "contracts/.cache/openzeppelin/4.5.0",
        "@safe": "contracts/.cache/safe/1.3.0",
        "@vault": "contracts/.cache/vault/v0.4.5",
        "@vaultmain": "contracts/.cache/vaultmain/master",
    }
    for key, value in expected.items():
        assert key in actual
        assert actual[key] == value


def test_get_import_remapping_handles_config(project, compiler):
    """
    Show you can override default remappings.
    Normally, these are deduced from dependencies, but you can change them
    and/or add new ones.
    """
    new_value = "NEW_VALUE"
    cfg = {
        "solidity": {
            "import_remapping": [
                "@dependency=dependency",  # Backwards compat!
                "@dependencyofdependency=dependencyofdependency/local",
                f"@vaultmain={new_value}",  # Changing a dependency
                f"@{new_value}={new_value}123",  # Adding something new
            ]
        },
        "dependencies": project.config.dependencies,
    }
    with project.temp_config(**cfg):
        actual = compiler.get_import_remapping(project=project)

    # Show it is backwards compatible (still works w/o changing cfg)
    assert actual["@dependency"] == "contracts/.cache/dependency/local"
    assert actual["@dependencyofdependency"] == "contracts/.cache/dependencyofdependency/local"
    # Show we can change a dependency.
    assert actual["@vaultmain"] == new_value
    # Show we can add a new remapping (quiet dependency).
    assert actual[f"@{new_value}"] == f"{new_value}123"
    # Show other dependency-deduced remappings still work.
    assert actual["@browniedependency"] == "contracts/.cache/browniedependency/local"


def test_get_imports(project, compiler):
    source_id = "contracts/ImportSourceWithEqualSignVersion.sol"
    path = project.sources.lookup(source_id)
    # Source (total) only has these 2 imports.
    expected = (
        "contracts/SpecificVersionWithEqualSign.sol",
        "contracts/CompilesOnce.sol",
    )
    actual = compiler.get_imports((path,), project=project)
    assert source_id in actual
    assert all(e in actual[source_id] for e in expected)


def test_get_imports_indirect(project, compiler):
    """
    Show that twice-removed indirect imports show up. This is required
    for accurate version mapping.
    """

    source_id = "contracts/IndirectlyImportingMoreConstrainedVersion.sol"
    path = project.sources.lookup(source_id)
    expected = (
        # These 2 are directly imported.
        "contracts/ImportSourceWithEqualSignVersion.sol",
        "contracts/IndirectlyImportingMoreConstrainedVersionCompanion.sol",
        # These are 2 are imported by the imported.
        "contracts/SpecificVersionWithEqualSign.sol",
        "contracts/CompilesOnce.sol",
    )
    actual = compiler.get_imports((path,), project=project)
    assert source_id in actual
    actual_str = ", ".join(list(actual[source_id]))
    for ex in expected:
        assert ex in actual[source_id], f"{ex} not in {actual_str}"


def test_get_imports_complex(project, compiler):
    """
    `contracts/Imports.sol` imports sources in every possible
    way. This test shows that we are able to detect all those
    unique ways of importing.
    """
    path = project.sources.lookup("contracts/Imports.sol")
    assert path is not None, "Failed to find Imports test contract."

    actual = compiler.get_imports((path,), project=project)
    expected = {
        "contracts/CompilesOnce.sol": [],
        "contracts/Imports.sol": [
            "contracts/.cache/browniedependency/local/contracts/BrownieContract.sol",
            "contracts/.cache/dependency/local/contracts/Dependency.sol",
            "contracts/.cache/dependencyofdependency/local/contracts/DependencyOfDependency.sol",
            "contracts/.cache/noncompilingdependency/local/contracts/CompilingContract.sol",
            "contracts/.cache/noncompilingdependency/local/contracts/subdir/SubCompilingContract.sol",  # noqa: E501
            "contracts/.cache/safe/1.3.0/contracts/common/Enum.sol",
            "contracts/CompilesOnce.sol",
            "contracts/MissingPragma.sol",
            "contracts/NumerousDefinitions.sol",
            "contracts/Source.extra.ext.sol",
            "contracts/subfolder/Relativecontract.sol",
        ],
        "contracts/MissingPragma.sol": [],
        "contracts/NumerousDefinitions.sol": [],
        "contracts/subfolder/Relativecontract.sol": [],
    }
    for base, imports in expected.items():
        assert base in actual
        assert actual[base] == imports


def test_get_imports_dependencies(project, compiler):
    """
    Show all the affected dependency contracts get included in the imports list.
    """
    source_id = "contracts/UseYearn.sol"
    path = project.sources.lookup(source_id)
    import_ls = compiler.get_imports((path,), project=project)
    actual = import_ls[source_id]
    token_path = "contracts/.cache/openzeppelin/4.5.0/contracts/token"
    expected = [
        f"{token_path}/ERC20/ERC20.sol",
        f"{token_path}/ERC20/IERC20.sol",
        f"{token_path}/ERC20/extensions/IERC20Metadata.sol",
        f"{token_path}/ERC20/utils/SafeERC20.sol",
        "contracts/.cache/openzeppelin/4.5.0/contracts/utils/Address.sol",
        "contracts/.cache/openzeppelin/4.5.0/contracts/utils/Context.sol",
        "contracts/.cache/vault/v0.4.5/contracts/BaseStrategy.sol",
        "contracts/.cache/vaultmain/master/contracts/BaseStrategy.sol",
    ]
    assert actual == expected


def test_get_imports_vyper_file(project, compiler):
    path = Path(__file__).parent / "contracts" / "RandomVyperFile.vy"
    assert path.is_file(), f"Setup failed - file not found {path}"
    with raises_because_not_sol:
        compiler.get_imports((path,))


def test_get_imports_full_project(project, compiler):
    paths = [x for x in project.sources.paths if x.suffix == ".sol"]
    actual = compiler.get_imports(paths, project=project)
    assert len(actual) > 0
    # Prove that every import source also is present in the import map.
    for imported_source_ids in actual.values():
        for source_id in imported_source_ids:
            assert source_id in actual, f"{source_id}'s imports not present."


def test_get_version_map(project, compiler):
    """
    Test that a strict version pragma is recognized in the version map.
    """
    path = project.sources.lookup("contracts/SpecificVersionWithEqualSign.sol")
    actual = compiler.get_version_map((path,), project=project)
    expected_version = Version("0.8.12+commit.f00d7308")
    expected_sources = ("SpecificVersionWithEqualSign",)
    assert expected_version in actual

    actual_ids = [x.stem for x in actual[expected_version]]
    assert all(e in actual_ids for e in expected_sources)


def test_get_version_map_importing_more_constrained_version(project, compiler):
    """
    Test that a strict version pragma in an imported source is recognized
    in the version map.
    """
    # This file's version is not super constrained, but it imports
    # a different source that does have a strict constraint.
    path = project.sources.lookup("contracts/ImportSourceWithEqualSignVersion.sol")

    actual = compiler.get_version_map((path,), project=project)
    expected_version = Version("0.8.12+commit.f00d7308")
    expected_sources = ("ImportSourceWithEqualSignVersion", "SpecificVersionWithEqualSign")
    assert expected_version in actual

    actual_ids = [x.stem for x in actual[expected_version]]
    assert all(e in actual_ids for e in expected_sources)


def test_get_version_map_indirectly_importing_more_constrained_version(project, compiler):
    """
    Test that a strict version pragma in a source imported by an imported
    source (twice removed) is recognized in the version map.
    """
    # This file's version is not super constrained, but it imports
    # a different source that imports another source that does have a constraint.
    path = project.sources.lookup("contracts/IndirectlyImportingMoreConstrainedVersion.sol")

    actual = compiler.get_version_map((path,), project=project)
    expected_version = Version("0.8.12+commit.f00d7308")
    expected_sources = (
        "IndirectlyImportingMoreConstrainedVersion",
        "ImportSourceWithEqualSignVersion",
        "SpecificVersionWithEqualSign",
    )
    assert expected_version in actual

    actual_ids = [x.stem for x in actual[expected_version]]
    assert all(e in actual_ids for e in expected_sources)


def test_get_version_map_dependencies(project, compiler):
    """
    Show all the affected dependency contracts get included in the version map.
    """
    source_id = "contracts/UseYearn.sol"
    older_example = "contracts/ImportOlderDependency.sol"
    paths = [project.sources.lookup(x) for x in (source_id, older_example)]
    actual = compiler.get_version_map(paths, project=project)

    fail_msg = f"versions: {', '.join([str(x) for x in actual])}"
    actual_len = len(actual)

    # Expecting one old version for ImportOlderDependency and one version for Yearn stuff.
    expected_len = 2

    if actual_len > expected_len:
        # Weird anomaly in CI/CD tests sometimes (at least at the time of write).
        # Including additional debug information.
        alt_map: dict = {}
        for version, src_ids in actual.items():
            for src_id in src_ids:
                if src_id in alt_map:
                    other_version = alt_map[src_id]
                    versions_str = ", ".join([str(other_version), str(version)])
                    pytest.fail(f"{src_id} in multiple version '{versions_str}'")
                else:
                    alt_map[src_id] = version

        # No duplicated versions found but still have unexpected extras.
        pytest.fail(f"Unexpected number of versions. {fail_msg}")

    elif actual_len < expected_len:
        pytest.fail(fail_msg)

    versions = sorted(list(actual.keys()))
    older = versions[0]  # Via ImportOlderDependency
    latest = versions[1]  # via UseYearn

    oz_token = "contracts/.cache/openzeppelin/4.5.0/contracts/token"
    expected_latest_source_ids = [
        f"{oz_token}/ERC20/ERC20.sol",
        f"{oz_token}/ERC20/IERC20.sol",
        f"{oz_token}/ERC20/extensions/IERC20Metadata.sol",
        f"{oz_token}/ERC20/utils/SafeERC20.sol",
        "contracts/.cache/openzeppelin/4.5.0/contracts/utils/Address.sol",
        "contracts/.cache/openzeppelin/4.5.0/contracts/utils/Context.sol",
        "contracts/.cache/vault/v0.4.5/contracts/BaseStrategy.sol",
        "contracts/.cache/vaultmain/master/contracts/BaseStrategy.sol",
        source_id,
    ]
    expected_older_source_ids = [
        "contracts/.cache/dependency/local/contracts/OlderDependency.sol",
        older_example,
    ]
    expected_latest_source_paths = {project.path / e for e in expected_latest_source_ids}
    expected_oldest_source_paths = {project.path / e for e in expected_older_source_ids}
    assert len(actual[latest]) == len(expected_latest_source_paths)
    assert actual[latest] == expected_latest_source_paths
    assert actual[older] == expected_oldest_source_paths


def test_get_version_map_picks_most_constrained_version(project, compiler):
    """
    Test that if given both a file that can compile at the latest version
    and a file that requires a lesser version but also imports the same file
    that could compile at the latest version, that they are all designated
    to compile using the lesser version.
    """
    source_ids = (
        "contracts/CompilesOnce.sol",
        "contracts/IndirectlyImportingMoreConstrainedVersion.sol",
    )
    paths = [project.sources.lookup(x) for x in source_ids]
    actual = compiler.get_version_map(paths, project=project)
    expected_version = Version("0.8.12+commit.f00d7308")
    assert expected_version in actual
    for path in paths:
        assert path in actual[expected_version], f"{path} is missing!"


def test_get_version_map_version_specified_in_config_file(compiler):
    path = Path(__file__).parent / "VersionSpecifiedInConfig"
    project = Project(path)
    paths = [p for p in project.sources.paths if p.suffix == ".sol"]
    actual = compiler.get_version_map(paths, project=project)
    expected_version = Version("0.8.12+commit.f00d7308")
    assert len(actual) == 1
    assert expected_version in actual
    assert len(actual[expected_version]) > 0


def test_get_version_map_raises_on_non_solidity_sources(project, compiler):
    path = project.contracts_folder / "RandomVyperFile.vy"
    with raises_because_not_sol:
        compiler.get_version_map((path,), project=project)


def test_get_version_map_full_project(project, compiler):
    paths = [x for x in project.sources.paths if x.suffix == ".sol"]
    actual = compiler.get_version_map(paths, project=project)
    latest = sorted(list(actual.keys()), reverse=True)[0]
    v0812 = Version("0.8.12+commit.f00d7308")
    vold = Version("0.4.26+commit.4563c3fc")
    assert v0812 in actual
    assert vold in actual

    v0812_1 = project.path / "contracts/ImportSourceWithEqualSignVersion.sol"
    v0812_2 = project.path / "contracts/IndirectlyImportingMoreConstrainedVersion.sol"

    assert v0812_1 in actual[v0812], "Constrained version files missing"
    assert v0812_2 in actual[v0812], "Constrained version files missing"

    # TDD: This was happening during development of 0.8.0.
    assert v0812_1 not in actual[latest], f"{v0812_1.stem} ended up in latest"
    assert v0812_2 not in actual[latest], f"{v0812_2.stem} ended up in latest"

    # TDD: Old file ending up in multiple spots.
    older_file = project.path / "contracts/.cache/dependency/local/contracts/OlderDependency.sol"
    assert older_file in actual[vold]
    for vers, fileset in actual.items():
        if vers == vold:
            continue

        assert older_file not in fileset, f"Oldest file also appears in version {vers}"


def test_get_compiler_settings(project, compiler):
    path = project.sources.lookup("contracts/Imports.sol")

    # Set this setting using an adhoc approach.
    compiler.compiler_settings["optimization_runs"] = 190

    actual = compiler.get_compiler_settings((path,), project=project)
    # No reason (when alone) to not use
    assert len(actual) == 1

    # 0.8.12 is hardcoded in some files, but none of those files should be here.
    version = next(iter(actual.keys()))
    assert version > Version("0.8.12+commit.f00d7308")

    settings = actual[version]
    assert settings["optimizer"] == {"enabled": True, "runs": 190}

    # NOTE: These should be sorted!
    assert settings["remappings"] == [
        "@browniedependency=contracts/.cache/browniedependency/local",
        "@dependency=contracts/.cache/dependency/local",
        "@dependencyofdependency=contracts/.cache/dependencyofdependency/local",
        # This remapping below was auto-corrected because imports were excluding contracts/ suffix.
        "@noncompilingdependency=contracts/.cache/noncompilingdependency/local/contracts",
        "@safe=contracts/.cache/safe/1.3.0",
        "browniedependency=contracts/.cache/browniedependency/local",
        "dependency=contracts/.cache/dependency/local",
        "dependencyofdependency=contracts/.cache/dependencyofdependency/local",
        "safe=contracts/.cache/safe/1.3.0",
    ]

    # Set in config.
    assert settings["evmVersion"] == "constantinople"

    # Should be all files (imports of imports etc.)
    actual_files = sorted(list(settings["outputSelection"].keys()))
    expected_files = [
        "contracts/.cache/browniedependency/local/contracts/BrownieContract.sol",
        "contracts/.cache/dependency/local/contracts/Dependency.sol",
        "contracts/.cache/dependencyofdependency/local/contracts/DependencyOfDependency.sol",
        "contracts/.cache/noncompilingdependency/local/contracts/CompilingContract.sol",
        "contracts/.cache/noncompilingdependency/local/contracts/subdir/SubCompilingContract.sol",
        "contracts/.cache/safe/1.3.0/contracts/common/Enum.sol",
        "contracts/CompilesOnce.sol",
        "contracts/Imports.sol",
        "contracts/MissingPragma.sol",
        "contracts/NumerousDefinitions.sol",
        "contracts/Source.extra.ext.sol",
        "contracts/subfolder/Relativecontract.sol",
    ]
    assert actual_files == expected_files

    # Output request is the same for all.
    expected_output_request = {
        "*": [
            "abi",
            "bin-runtime",
            "devdoc",
            "userdoc",
            "evm.bytecode.object",
            "evm.bytecode.sourceMap",
            "evm.deployedBytecode.object",
        ],
        "": ["ast"],
    }
    for output in settings["outputSelection"].values():
        assert output == expected_output_request


def test_get_standard_input_json(project, compiler):
    paths = [x for x in project.sources.paths if x.suffix == ".sol"]
    actual = compiler.get_standard_input_json(paths, project=project)
    v0812 = Version("0.8.12+commit.f00d7308")
    v056 = Version("0.5.16+commit.9c3226ce")
    v0426 = Version("0.4.26+commit.4563c3fc")
    latest = sorted(list(actual.keys()), reverse=True)[0]

    fail_msg = f"Versions: {', '.join([str(v) for v in actual])}"
    assert v0812 in actual, fail_msg
    assert v056 in actual, fail_msg
    assert v0426 in actual, fail_msg
    assert latest in actual, fail_msg

    v0812_sources = list(actual[v0812]["sources"].keys())
    v056_sources = list(actual[v056]["sources"].keys())
    v0426_sources = list(actual[v0426]["sources"].keys())
    latest_sources = list(actual[latest]["sources"].keys())

    assert "contracts/ImportSourceWithEqualSignVersion.sol" not in latest_sources
    assert "contracts/IndirectlyImportingMoreConstrainedVersion.sol" not in latest_sources

    # Some source expectations.
    assert "contracts/CompilesOnce.sol" in v0812_sources
    assert "contracts/SpecificVersionRange.sol" in v0812_sources
    assert "contracts/ImportSourceWithNoPrefixVersion.sol" in v0812_sources

    assert "contracts/OlderVersion.sol" in v056_sources
    assert "contracts/ImportOlderDependency.sol" in v0426_sources
    assert "contracts/.cache/dependency/local/contracts/OlderDependency.sol" in v0426_sources


def test_compile(project, compiler):
    path = project.sources.lookup("contracts/Imports.sol")
    actual = [c for c in compiler.compile((path,), project=project)]
    # We only get back the contracts we requested, even if it had to compile
    # others (like imports) to get it to work.
    assert len(actual) == 1
    assert isinstance(actual[0], ContractType)
    assert actual[0].name == "Imports"
    assert actual[0].source_id == "contracts/Imports.sol"
    assert actual[0].deployment_bytecode is not None
    assert actual[0].runtime_bytecode is not None
    assert len(actual[0].abi) > 0


def test_compile_performance(benchmark, compiler, project):
    """
    See https://pytest-benchmark.readthedocs.io/en/latest/
    """
    path = project.sources.lookup("contracts/MultipleDefinitions.sol")
    result = benchmark.pedantic(
        lambda *args, **kwargs: [x for x in compiler.compile(*args, **kwargs)],
        args=((path,),),
        kwargs={"project": project},
        rounds=1,
    )
    assert len(result) > 0


def test_compile_multiple_definitions_in_source(project, compiler):
    """
    Show that if multiple contracts / interfaces are defined in a single
    source, that we get all of them when compiling.
    """
    source_id = "contracts/MultipleDefinitions.sol"
    path = project.sources.lookup(source_id)
    result = [c for c in compiler.compile((path,), project=project)]
    assert len(result) == 2
    assert [r.name for r in result] == ["IMultipleDefinitions", "MultipleDefinitions"]
    assert all(r.source_id == source_id for r in result)

    assert project.MultipleDefinitions
    assert project.IMultipleDefinitions


def test_compile_contract_with_different_name_than_file(project, compiler):
    source_id = "contracts/DifferentNameThanFile.sol"
    path = project.sources.lookup(source_id)
    actual = [c for c in compiler.compile((path,), project=project)]
    assert len(actual) == 1
    assert actual[0].source_id == source_id


def test_compile_only_returns_contract_types_for_inputs(project, compiler):
    """
    Test showing only the requested contract types get returned.
    """
    path = project.sources.lookup("contracts/Imports.sol")
    contract_types = [c for c in compiler.compile((path,), project=project)]
    assert len(contract_types) == 1
    assert contract_types[0].name == "Imports"


def test_compile_vyper_contract(project, compiler):
    path = project.contracts_folder / "RandomVyperFile.vy"
    with raises_because_not_sol:
        _ = [c for c in compiler.compile((path,), project=project)]


def test_compile_just_a_struct(compiler, project):
    """
    Before, you would get a nasty index error, even though this is valid Solidity.
    The fix involved using nicer access to "contracts" in the standard output JSON.
    """
    path = project.sources.lookup("contracts/JustAStruct.sol")
    contract_types = [c for c in compiler.compile((path,), project=project)]
    assert len(contract_types) == 0


def test_compile_produces_source_map(project, compiler):
    path = project.sources.lookup("contracts/MultipleDefinitions.sol")
    result = [c for c in compiler.compile((path,), project=project)][-1]
    assert result.sourcemap.root == "124:87:0:-:0;;;;;;;;;;;;;;;;;;;"


def test_compile_via_ir(project, compiler):
    path = project.contracts_folder / "StackTooDep.sol"
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
    path.write_text(source_code)

    try:
        [c for c in compiler.compile((path,), project=project)]
    except Exception as e:
        assert "Stack too deep" in str(e)

    with project.temp_config(solidity={"via_ir": True}):
        _ = [c for c in compiler.compile((path,), project=project)]

        # delete source code file
        path.unlink()


@pytest.mark.install
def test_installs_from_compile(project, compiler, temp_solcx_path):
    """
    Test the compilation of a contract with no defined pragma spec.

    The plugin should implicitly download the latest version to compile the
    contract with. `temp_solcx_path` is used to simulate an environment without
    compilers installed.
    """
    assert not solcx.get_installed_solc_versions()
    path = project.sources.lookup("contracts/MissingPragma.sol")
    contract_types = [c for c in compiler.compile((path,), project=project)]
    assert len(contract_types) == 1
    installed_versions = solcx.get_installed_solc_versions()
    assert len(installed_versions) == 1
    assert installed_versions[0] == max(solcx.get_installable_solc_versions())


def test_compile_project(project, compiler):
    """
    Simple test showing the full project indeed compiles.
    """
    paths = [x for x in project.sources.paths if get_full_extension(x) == ".sol"]
    actual = [c for c in compiler.compile(paths, project=project)]
    assert len(actual) > 0


def test_compile_outputs_compiler_data_to_manifest(project, compiler):
    project.update_manifest(compilers=[])
    path = project.sources.lookup("contracts/CompilesOnce.sol")
    _ = [c for c in compiler.compile((path,), project=project)]
    assert len(project.manifest.compilers or []) == 1
    actual = project.manifest.compilers[0]
    assert actual.name == "solidity"
    assert "CompilesOnce" in actual.contractTypes
    assert actual.version == "0.8.26+commit.8a97fa7a"
    # Compiling again should not add the same compiler again.
    _ = [c for c in compiler.compile((path,), project=project)]
    length_again = len(project.manifest.compilers or [])
    assert length_again == 1


def test_add_library(project, account, compiler, connection):
    # Does not exist yet because library is not deployed or known.
    with pytest.raises(AttributeError):
        _ = project.ContractUsingLibraryInSameSource
    with pytest.raises(AttributeError):
        _ = project.ContractUsingLibraryNotInSameSource

    library = project.ExampleLibrary.deploy(sender=account)
    compiler.add_library(library, project=project)

    # After deploying and adding the library, we can use contracts that need it.
    assert project.ContractUsingLibraryNotInSameSource
    assert project.ContractUsingLibraryInSameSource


def test_enrich_error_when_custom(compiler, project, owner, not_owner, connection):
    path = project.sources.lookup("contracts/HasError.sol")
    _ = [c for c in compiler.compile((path,), project=project)]

    # Deploy so Ape know about contract type.
    contract = owner.deploy(project.HasError, 1)
    with pytest.raises(contract.Unauthorized) as err:
        contract.withdraw(sender=not_owner)

    assert err.value.inputs == {"addr": not_owner.address, "counter": 123}


def test_enrich_error_when_custom_in_constructor(compiler, project, owner, not_owner, connection):
    # Deploy so Ape know about contract type.
    with reverts(project.HasError.Unauthorized) as err:
        not_owner.deploy(project.HasError, 0)

    assert err.value.inputs == {"addr": not_owner.address, "counter": 123}


def test_enrich_error_when_builtin(project, owner, connection):
    contract = project.BuiltinErrorChecker.deploy(sender=owner)
    with pytest.raises(IndexOutOfBoundsError):
        contract.checkIndexOutOfBounds(sender=owner)


def test_flatten(mocker, project, compiler):
    path = project.contracts_folder / "Imports.sol"
    base_expected = Path(__file__).parent / "data"

    # NOTE: caplog for some reason is inconsistent and causes flakey tests.
    #  Thus, we are using our own "logger_spy".
    logger_spy = mocker.patch("ape_solidity.compiler.logger")

    res = compiler.flatten_contract(path, project=project)
    call_args = logger_spy.warning.call_args
    actual_logs = call_args[0] if call_args else ()
    assert actual_logs, f"Missing warning logs from dup-licenses, res: {res}"
    actual = actual_logs[-1]
    # NOTE: MIT coming from Imports.sol and LGPL-3.0-only coming from
    #   @safe/contracts/common/Enum.sol.
    expected = (
        "Conflicting licenses found: 'LGPL-3.0-only, MIT'. Using the root file's license 'MIT'."
    )
    assert actual == expected

    path = project.contracts_folder / "ImportingLessConstrainedVersion.sol"
    flattened_source = compiler.flatten_contract(path, project=project)
    flattened_source_path = base_expected / "ImportingLessConstrainedVersionFlat.sol"

    actual = str(flattened_source)
    expected = str(flattened_source_path.read_text())
    assert actual == expected


def test_compile_code(project, compiler):
    code = """
contract Contract {
    function snakes() pure public returns(bool) {
        return true;
    }
}
"""
    actual = compiler.compile_code(code, project=project, contractName="TestContractName")
    assert actual.name == "TestContractName"
    assert len(actual.abi) > 0
    assert actual.ast is not None
    assert len(actual.runtime_bytecode.bytecode) > 0
    assert len(actual.deployment_bytecode.bytecode) > 0
