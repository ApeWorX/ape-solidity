// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

contract FixBugWhereCompiledTwice {
    function foo() pure public returns(bool) {
        return true;
    }
}
