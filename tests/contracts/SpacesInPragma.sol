// This file exists to test a bug that occurred when the user has a pragma
// like this one. It was failing to register as a proper NpmSpec because
// of the spaces between the operator and the version.
pragma solidity >= 0.4.19 < 0.7.0;

contract SpacesInPragma {
    function foo() pure public returns(bool) {
        return true;
    }
}
