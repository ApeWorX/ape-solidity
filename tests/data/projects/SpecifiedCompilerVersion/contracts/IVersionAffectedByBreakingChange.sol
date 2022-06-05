// SPDX-License-Identifier: MIT

pragma solidity ^0.8.0;

abstract contract IVersionAffectedByBreakingChange {
    function hashProposal(
            address[] calldata targets,
            uint256[] calldata values,
            bytes[] calldata calldatas,
            bytes32 descriptionHash
        ) public pure virtual returns (uint256);
}
