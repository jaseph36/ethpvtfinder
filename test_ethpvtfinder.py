# tests/test_ethpvtfinder.py
import unittest
from ethpvtfinder import ethpvtfinder

class TestEthPvtFinder(unittest.TestCase):

    def test_is_valid_private_key(self):
        self.assertTrue(ethpvtfinder.is_valid_private_key("e5b7e99958b556d459955f8ff55d575d07f655f55d45955f8ff55d575d07f6"))
        self.assertFalse(ethpvtfinder.is_valid_private_key("xyz123"))

    # Add more test cases for other functions as needed

if __name__ == '__main__':
    unittest.main()
