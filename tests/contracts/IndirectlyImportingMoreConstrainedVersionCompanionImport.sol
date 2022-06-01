// SPDX-License-Identifier: MIT

pragma solidity ^0.8.12;

// This file exists to test that when we import a file with another more constraining import,
// that the files other imports (e.g. IndirectlyImportingMoreContrainedVersionCompanion.sol)
// uses the constrained version as well as that files imports, which is this file.

contract IndirectlyImportingMoreConstrainedVersionCompanionImport {
    function foo() pure public returns(bool) {
        return true;
    }
}
