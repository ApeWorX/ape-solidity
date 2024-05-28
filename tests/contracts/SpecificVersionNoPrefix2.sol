// SPDX-License-Identifier: MIT

// NOTE: This contract purposely is the same as `SpecificVersionNoPrefix`
// except with a different specific version.
pragma solidity 0.8.14;

// Both specific versions import the same file.
// This is an important test!
import "contracts/CompilesOnce.sol";

contract SpecificVersionNoPrefix2 {
    function foo() pure public returns(bool) {
        return true;
    }
}
