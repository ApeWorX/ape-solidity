// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import * as Depend from "@dependency/contracts/Dependency.sol";
import
    "./././././././././././././././././././././././././././././././././././MissingPragma.sol";
import { MyStruct } from "contracts/CompilesOnce.sol";
import "./subfolder/Relativecontract.sol";
import "@dependency/contracts/Dependency.sol" as Depend2;
import "@browniedependency/contracts/BrownieContract.sol";
import {
    Struct0,
    Struct1,
    Struct2,
    Struct3,
    Struct4,
    Struct5
} from "./NumerousDefinitions.sol";
import "@noncompilingdependency/CompilingContract.sol";
// Purposely repeat an import to test how the plugin handles that.
import "@noncompilingdependency/CompilingContract.sol";

import "@safe/contracts/common/Enum.sol";

// Purposely exclude the contracts folder to test older Ape-style project imports.
import "@noncompilingdependency/subdir/SubCompilingContract.sol";

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.
import "./Source.extra.ext.sol";

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
