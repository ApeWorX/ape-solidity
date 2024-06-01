// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "contracts/CircularImport2.sol";

contract CircularImport1 {
    function foo() pure public returns(bool) {
        return true;
    }
}
