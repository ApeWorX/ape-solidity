// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
