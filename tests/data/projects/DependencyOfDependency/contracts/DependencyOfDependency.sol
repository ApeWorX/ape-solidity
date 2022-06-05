// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

contract DependencyOfDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
