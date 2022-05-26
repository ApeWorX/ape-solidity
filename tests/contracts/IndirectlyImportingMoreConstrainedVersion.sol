// SPDX-License-Identifier: MIT

pragma solidity ^0.8.4;

import "./ImportSourceWithEqualSignVersion.sol";

contract IndirectlyImportingMoreConstrainedVersion {
    function foo() pure public returns(bool) {
        return true;
    }
}
