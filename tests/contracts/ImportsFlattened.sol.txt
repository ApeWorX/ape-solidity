// SPDX-License-Identifier: MIT

// File: @remapping_2_brownie/BrownieContract.sol

pragma solidity ^0.8.4;

contract BrownieContract {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @styleofbrownie/BrownieStyleDependency.sol

pragma solidity ^0.8.4;

contract BrownieStyleDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @dependency_remapping/DependencyOfDependency.sol

pragma solidity ^0.8.4;

contract DependencyOfDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @remapping/contracts/Dependency.sol

pragma solidity ^0.8.4;


struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @dependency_remapping/DependencyOfDependency.sol

pragma solidity ^0.8.4;

contract DependencyOfDependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: @remapping_2/Dependency.sol

pragma solidity ^0.8.4;


struct DependencyStruct {
    string name;
    uint value;
}

contract Dependency {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: CompilesOnce.sol

pragma solidity >=0.8.0;

struct MyStruct {
    string name;
    uint value;
}

contract CompilesOnce {
    // This contract tests the scenario when we have a contract with
    // a similar compiler version to more than one other contract's.
    // This ensures we don't compile the same contract more than once.

    function foo() pure public returns(bool) {
        return true;
    }
}

// File: ./././././././././././././././././././././././././././././././././././MissingPragma.sol

contract MissingPragma {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: ./NumerousDefinitions.sol

pragma solidity >=0.8.0;

struct Struct0 {
    string name;
    uint value;
}

struct Struct1 {
    string name;
    uint value;
}

struct Struct2 {
    string name;
    uint value;
}

struct Struct3 {
    string name;
    uint value;
}

struct Struct4 {
    string name;
    uint value;
}

struct Struct5 {
    string name;
    uint value;
}

contract NumerousDefinitions {
    function foo() pure public returns(bool) {
        return true;
    }
}

// File: ./subfolder/Relativecontract.sol

pragma solidity >=0.8.0;

contract Relativecontract {

    function foo() pure public returns(bool) {
        return true;
    }
}

// File: Imports.sol

pragma solidity ^0.8.4;


contract Imports {
    function foo() pure public returns(bool) {
        return true;
    }
}
