// SPDX-License-Identifier: GPL-3.0
pragma solidity ^0.8.4;

error Unauthorized(address addr, uint256 counter);

contract HasError {
    address payable owner = payable(msg.sender);

    constructor(uint256 value) {
        if (value == 0) {
            revert Unauthorized(msg.sender, 123);
        }
    }

    function withdraw() public {
        if (msg.sender != owner)
            revert Unauthorized(msg.sender, 123);

        owner.transfer(address(this).balance);
    }
    // ...
}
