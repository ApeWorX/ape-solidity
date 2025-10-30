contract CheckSetup {
    uint256 store;

    function setUp() external {
        store = 1;
    }

    function test_setUp_works() external {
        require(store == 1);
    }
}
