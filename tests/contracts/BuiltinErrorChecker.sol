// SPDX-License-Identifier: MIT
pragma solidity ^0.8.2;

contract BuiltinErrorChecker {
    uint256[] public _arr;

    function checkIndexOutOfBounds() view public returns(uint256) {
        return _arr[2];
    }
}
