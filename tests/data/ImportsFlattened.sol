pragma solidity ^0.8.4;
// SPDX-License-Identifier: MIT

// File: @dependencyofdependency/contracts/DependencyOfDependency.sol

contract DependencyOfDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: * as Depend from "@dependency/contracts/Dependency.sol

struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
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
// File: @noncompilingdependency/CompilingContract.sol

contract BrownieStyleDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
// File: @browniedependency/contracts/BrownieContract.sol

contract CompilingContract {
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
// File: ./././././././././././././././././././././././././././././././././././MissingPragma.sol

contract MissingPragma {
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
// File: ./Source.extra.ext.sol

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.
contract SourceExtraExt {
    function foo() pure public returns(bool) {
        return true;
    }
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
// File: @noncompilingdependency/subdir/SubCompilingContract.sol

contract SubCompilingContract {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: Imports.sol

import
    "./././././././././././././././././././././././././././././././././././MissingPragma.sol";
import {
    Struct0,
    Struct1,
    Struct2,
    Struct3,
    Struct4,
    Struct5
} from "./NumerousDefinitions.sol";
// Purposely repeat an import to test how the plugin handles that.

// Purposely exclude the contracts folder to test older Ape-style project imports.

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
