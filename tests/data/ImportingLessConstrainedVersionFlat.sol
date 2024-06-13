pragma solidity =0.8.12;
// SPDX-License-Identifier: MIT

// File: ./SpecificVersionRange.sol

contract SpecificVersionRange {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: ImportingLessConstrainedVersion.sol

// The file we are importing specific range '>=0.8.12 <0.8.15';
// This means on its own, the plugin would use 0.8.14 if its installed.
// However - it should use 0.8.12 because of this file's requirements.

contract ImportingLessConstrainedVersion {
    function foo() pure public returns(bool) {
        return true;
    }
}
