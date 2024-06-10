// SPDX-License-Identifier: MIT
pragma solidity ^0.8.4;

// Showing sources with extra extensions are by default excluded,
// unless used as an import somewhere in a non-excluded source.
contract SourceExtraExt {
    function foo() pure public returns(bool) {
        return true;
    }
}
