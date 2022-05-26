// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

// The file SpecificVersion.sol has pragma spec =0.8.12.
// This means that these files should all compile using that version.
import "SpecificVersion.sol";
import "CompilesOnce.sol";

contract ImportConstrainingVersion {
    function foo() pure public returns(bool) {
        return true;
    }
}
