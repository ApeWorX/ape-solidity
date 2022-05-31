// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "@remapping/contracts/Dependency.sol";

contract UsingDependencyWithinSubFolder {
    function foo() pure public returns(bool) {
        return true;
    }
}
