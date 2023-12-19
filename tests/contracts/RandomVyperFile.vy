# @version 0.3.10

# NOTE: This file only exists to prove it does not interfere
#  (we had found bugs related to this)

myNumber: public(uint256)

@external
def setNumber(num: uint256):
    self.myNumber = num
