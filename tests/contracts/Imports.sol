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
import "@noncompilingdependency/contracts/CompilingContract.sol";
// Purposely repeat an import to test how the plugin handles that.
import "@noncompilingdependency/contracts/CompilingContract.sol";

import "@safe/contracts/common/Enum.sol";

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
