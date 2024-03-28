// SPDX-License-Identifier: MIT

pragma solidity 0.8.12;

import "./CompilesOnce.sol";

contract SpecificVersionNoPrefix {
    function foo() pure public returns(bool) {
        return true;
    }
}
