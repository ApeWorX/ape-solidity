// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "@remapping/Dependency.sol";
import "@remapping_2/Dependency.sol";
import "CompilesOnce.sol";

contract Solcontract {
    function foo() pure public returns(bool) {
        return true;
    }
}
