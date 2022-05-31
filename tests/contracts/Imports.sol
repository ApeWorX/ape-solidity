// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import * as Depend from "@remapping/contracts/Dependency.sol";
import { MyStruct } from "CompilesOnce.sol";
import "./subfolder/Relativecontract.sol";
import "@remapping_2/Dependency.sol" as Depend2;
import "@brownie/BrownieContract.sol";

contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
