// SPDX-License-Identifier: MIT
// This file exists to test a bug that occurred when the user has a pragma
// like this one. It was failing to register as a proper NpmSpec because
// of the spaces between the operator and the version.
pragma solidity >= 0.4.19 < 0.5.0;

interface SpacesInPragma {
  // This syntax fails on version >= 5.0, thus we are testing
  // that we don't default to our latest solidity version.
  function foo(bytes32 node) public view returns (uint64);
}
