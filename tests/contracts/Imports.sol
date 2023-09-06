// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import * as Depend from "@remapping/contracts/Dependency.sol";
import
    "./././././././././././././././././././././././././././././././././././MissingPragma.sol";
import { MyStruct } from "CompilesOnce.sol";
import "./subfolder/Relativecontract.sol";
import "@remapping_2/Dependency.sol" as Depend2;
import "@remapping_2_brownie/BrownieContract.sol";
import {
    Struct0,
    Struct1,
    Struct2,
    Struct3,
    Struct4,
    Struct5
} from "./NumerousDefinitions.sol";
import "@styleofbrownie/BrownieStyleDependency.sol";
// Purposely repeat an import to test how the plugin handles that.
import "@styleofbrownie/BrownieStyleDependency.sol";

import "@gnosis/common/Enum.sol";

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
