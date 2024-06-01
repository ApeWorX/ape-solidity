// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "contracts/CircularImport1.sol";

contract CircularImport2 {
    function foo() pure public returns(bool) {
        return true;
    }
}
