// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "../Dependency.sol";
import "../subfolder/InDependencySubfolder.sol";

contract InDependencySubfolderWithImports {
    function foo() pure public returns(bool) {
        return true;
    }
}
