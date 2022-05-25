// SPDX-License-Identifier: MIT

pragma solidity >=0.8.0;

struct MyStruct {
    string name;
    uint value;
}

contract CompilesOnce {
    // This contract tests the scenario when we have a contract with
    // a similar compiler version to more than one other contract's.
    // This ensures we don't compile the same contract more than once.

    function foo() pure public returns(bool) {
        return true;
    }
}
