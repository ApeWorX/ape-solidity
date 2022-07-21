// SPDX-License-Identifier: MIT

pragma solidity ^0.8.12;

interface IMultipleDefinitions {
    function foo() external;
}

contract MultipleDefinitions is IMultipleDefinitions {
    function foo() external {}
}
