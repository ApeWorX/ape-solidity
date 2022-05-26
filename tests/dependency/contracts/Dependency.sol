// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
