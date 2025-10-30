contract BasicFunctionality {
    function test_it_works() external {}

    function test_it_raises() external {
        /// @pytest.mark.xfail
        require(false, "It works!");
    }
}
