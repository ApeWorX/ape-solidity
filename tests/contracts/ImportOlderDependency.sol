// SPDX-License-Identifier: MIT

import "@remapping/contracts/OlderDependency.sol";

contract ImportOlderDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}
