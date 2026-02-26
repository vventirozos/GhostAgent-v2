import pytest
import sys
from unittest.mock import patch, MagicMock
from ghost_agent.main import parse_args

def test_parse_args_coding_nodes():
    # Simulate command line arguments
    test_args = ["main.py", "--coding-nodes", "http://node1:8000,http://node2:8000"]
    
    with patch.object(sys, "argv", test_args):
        args = parse_args()
        
    assert args.coding_nodes == "http://node1:8000,http://node2:8000"
    
def test_parse_args_coding_nodes_missing():
    # Simulate command line arguments without coding nodes
    test_args = ["main.py"]
    
    with patch.object(sys, "argv", test_args):
        args = parse_args()
        
    assert args.coding_nodes is None
