// SPDX-License-Identifier: MIT

// This version claims to work in the whole 0.8.0 range.
// However, it fails on 0.8.14. This was a problem noticed
// in older open-zeppelin releases. To use older releases with
// this problem, you can manually configure the compiler version.
//
// The issue on 0.8.14 is: "Data locations of parameters have to
// be the same when overriding non-external functions".

pragma solidity ^0.8.0;

import "./IVersionAffectedByBreakingChange.sol";

contract VersionAffectedByBreakingChange is IVersionAffectedByBreakingChange {
    function hashProposal(
        address[] memory targets,
        uint256[] memory values,
        bytes[] memory calldatas,
        bytes32 descriptionHash
    ) public pure virtual override returns (uint256) {
        return uint256(keccak256(abi.encode(targets, values, calldatas, descriptionHash)));
    }
}
