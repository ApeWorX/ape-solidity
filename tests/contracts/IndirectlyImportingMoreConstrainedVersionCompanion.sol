// SPDX-License-Identifier: MIT

pragma solidity ^0.8.12;

// We are testing this files imports are constrained by the version
// of the file importing this file (which is constrained by another one of
// its imports).
import "./IndirectlyImportingMoreConstrainedVersionCompanionImport.sol";

contract IndirectlyImportingMoreConstrainedVersionCompanion {
    function foo() pure public returns(bool) {
        return true;
    }
}
