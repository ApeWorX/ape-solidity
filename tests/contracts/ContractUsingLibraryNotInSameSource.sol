// SPDX-License-Identifier: GPL-3.0
// Borrowed from Solidity documentation.
pragma solidity >=0.6.0 <0.9.0;

import "./LibraryFun.sol";

contract ContractUsingLibraryNotInSameSource {
    Data knownValues;

    function register(uint value) public {
        // The library functions can be called without a
        // specific instance of the library, since the
        // "instance" will be the current contract.
        require(ExampleLibrary.insert(knownValues, value));
    }
    // In this contract, we can also directly access knownValues.flags, if we want.
}
