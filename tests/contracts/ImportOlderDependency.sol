// SPDX-License-Identifier: MIT

import "@dependency/contracts/OlderDependency.sol";

contract ImportOlderDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
