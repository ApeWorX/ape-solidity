// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "@dependencyofdependency/contracts/DependencyOfDependency.sol";

struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
