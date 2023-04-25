// SPDX-License-Identifier: GPL-3.0
pragma solidity >=0.8.17;

import {VaultAPI} from "@vault/BaseStrategy.sol";
import {VaultAPI as VaultMain} from "@vaultmain/BaseStrategy.sol";


interface UseYearn is VaultAPI {
    function name() override external view returns (string calldata);
}
