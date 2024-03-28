// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

// The file SpecificVersionWithEqualSign.sol has pragma spec '=0.8.12'.
// This means that these files should all compile using that version.
import "contracts/SpecificVersionWithEqualSign.sol";
import "contracts/CompilesOnce.sol";

contract ImportSourceWithEqualSignVersion {
    function foo() pure public returns(bool) {
        return true;
    }
}
