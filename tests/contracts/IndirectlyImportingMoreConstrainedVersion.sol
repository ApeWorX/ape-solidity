// SPDX-License-Identifier: MIT

pragma solidity ^0.8.12;

import "./ImportSourceWithEqualSignVersion.sol";
import "./IndirectlyImportingMoreConstrainedVersionCompanion.sol";

contract IndirectlyImportingMoreConstrainedVersion {
    function foo() pure public returns(bool) {
        return true;
    }
}
