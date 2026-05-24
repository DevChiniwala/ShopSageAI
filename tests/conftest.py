"""
Pytest configuration — ensures project root is in sys.path.
"""
import sys
import os

# Add project root to path so 'shopsage' package can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
