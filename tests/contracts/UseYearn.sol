// SPDX-License-Identifier: GPL-3.0
pragma solidity >=0.6.11;

import {VaultAPI} from "@vault/BaseStrategy.sol";


interface ApeWorXVault is VaultAPI {
    function name() override external view returns (string calldata);
}
