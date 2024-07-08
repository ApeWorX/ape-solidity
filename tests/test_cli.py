import subprocess

from ape.utils import create_tempdir

from ape_solidity._cli import cli

EXPECTED_FLATTENED_CONTRACT = """
pragma solidity ^0.8.4;
// SPDX-License-Identifier: MIT

// File: @browniedependency/contracts/BrownieContract.sol

contract CompilingContract {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: @dependencyofdependency/contracts/DependencyOfDependency.sol

contract DependencyOfDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @dependency/contracts/Dependency.sol" as Depend2

struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: @noncompilingdependency/CompilingContract.sol

contract BrownieStyleDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: @noncompilingdependency/subdir/SubCompilingContract.sol

contract SubCompilingContract {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: @safe/contracts/common/Enum.sol

/// @title Enum - Collection of enums
/// @author Richard Meissner - <richard@gnosis.pm>
contract Enum {
    enum Operation {Call, DelegateCall}
}
// File: { MyStruct } from "contracts/CompilesOnce.sol

struct MyStruct {
    string name;
    uint value;
}

contract CompilesOnce {
    // This contract tests the scenario when we have a contract with
    // a similar compiler version to more than one other contract's.
    // This ensures we don't compile the same contract more than once.

    function foo() pure public returns(bool) {
        return true;
    }
}
// File: ./././././././././././././././././././././././././././././././././././MissingPragma.sol

contract MissingPragma {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: { Struct0, Struct1, Struct2, Struct3, Struct4, Struct5 } from "./NumerousDefinitions.sol

struct Struct0 {
    string name;
    uint value;
}

struct Struct1 {
    string name;
    uint value;
}

struct Struct2 {
    string name;
    uint value;
}

struct Struct3 {
    string name;
    uint value;
}

struct Struct4 {
    string name;
    uint value;
}

struct Struct5 {
    string name;
    uint value;
}

contract NumerousDefinitions {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: ./Source.extra.ext.sol

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.
contract SourceExtraExt {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: ./subfolder/Relativecontract.sol

contract Relativecontract {

    function foo() pure public returns(bool) {
        return true;
    }
}

// File: Imports.sol

// Purposely repeat an import to test how the plugin handles that.

// Purposely exclude the contracts folder to test older Ape-style project imports.

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
""".strip()


def test_cli_flatten(project, cli_runner):
    path = project.contracts_folder / "Imports.sol"
    arguments = ["flatten", str(path)]
    end = ("--project", str(project.path))
    with create_tempdir() as tmpdir:
        file = tmpdir / "Imports.sol"
        arguments.extend([str(file), *end])
        result = cli_runner.invoke(cli, arguments, catch_exceptions=False)
        assert result.exit_code == 0, result.stderr_bytes
        output = file.read_text(encoding="utf8").strip()
        assert output == EXPECTED_FLATTENED_CONTRACT


def test_compile():
    """
    Integration: Testing the CLI using an actual subprocess because
    it is the only way to test compiling the project such that it
    isn't treated as a tempdir project.
    """
    # Use a couple contracts
    cmd_ls = ("ape", "compile", "subdir", "--force")
    completed_process = subprocess.run(cmd_ls, capture_output=True)
    output = completed_process.stdout.decode(encoding="utf8")
    assert completed_process.returncode == 0
    assert "SUCCESS" in output
