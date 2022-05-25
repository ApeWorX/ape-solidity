// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import * as Depend from "@remapping/Dependency.sol";
import { MyStruct } from "CompilesOnce.sol";
import "./folder/Relativecontract.sol";
import "@remapping_2/Dependency.sol" as Depend2;

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
