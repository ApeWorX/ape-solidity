// SPDX-License-Identifier: MIT

pragma solidity =0.8.12;

import "CompilesOnce.sol";

contract SpecificVersionWithEqualSign {
    function foo() pure public returns(bool) {
        return true;
    }
}
