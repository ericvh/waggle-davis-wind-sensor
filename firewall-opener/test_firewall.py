#!/usr/bin/env python3

"""
Test script for firewall manager
"""

import socket
import sys
import time
from firewall_manager import FirewallManager


def test_port_binding(port):
    """Test if we can bind to the port"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.close()
        return True
    except Exception as e:
        print(f"Port binding test failed: {e}")
        return False


def main():
    """Test the firewall manager"""
    port = 50222
    
    print("🧪 Testing Firewall Manager")
    print("=" * 30)
    
    # Test 1: Initial port binding
    print(f"Test 1: Initial port binding test on port {port}")
    initial_binding = test_port_binding(port)
    print(f"Result: {'✓ Can bind' if initial_binding else '✗ Cannot bind'}")
    print()
    
    # Test 2: Setup firewall
    print(f"Test 2: Setting up firewall for port {port}")
    firewall_manager = FirewallManager(port=port)
    setup_success = firewall_manager.setup_firewall()
    print(f"Result: {'✓ Setup successful' if setup_success else '✗ Setup failed'}")
    print()
    
    # Test 3: Port binding after setup
    print(f"Test 3: Port binding test after setup")
    after_setup_binding = test_port_binding(port)
    print(f"Result: {'✓ Can bind' if after_setup_binding else '✗ Cannot bind'}")
    print()
    
    # Test 4: Check rule exists
    print(f"Test 4: Checking if rule exists")
    rule_exists = firewall_manager._rule_exists()
    print(f"Result: {'✓ Rule exists' if rule_exists else '✗ Rule does not exist'}")
    print()
    
    # Test 5: Get status
    print(f"Test 5: Getting firewall status")
    status_success = firewall_manager.get_status()
    print(f"Result: {'✓ Status check successful' if status_success else '✗ Status check failed'}")
    print()
    
    # Test 6: Cleanup
    print(f"Test 6: Cleaning up firewall rules")
    cleanup_success = firewall_manager.remove_rule()
    print(f"Result: {'✓ Cleanup successful' if cleanup_success else '✗ Cleanup failed'}")
    print()
    
    # Test 7: Port binding after cleanup
    print(f"Test 7: Port binding test after cleanup")
    after_cleanup_binding = test_port_binding(port)
    print(f"Result: {'✓ Can bind' if after_cleanup_binding else '✗ Cannot bind'}")
    print()
    
    # Summary
    print("📊 Test Summary")
    print("=" * 30)
    print(f"Initial binding: {'✓' if initial_binding else '✗'}")
    print(f"Setup success: {'✓' if setup_success else '✗'}")
    print(f"After setup binding: {'✓' if after_setup_binding else '✗'}")
    print(f"Rule exists: {'✓' if rule_exists else '✗'}")
    print(f"Status check: {'✓' if status_success else '✗'}")
    print(f"Cleanup success: {'✓' if cleanup_success else '✗'}")
    print(f"After cleanup binding: {'✓' if after_cleanup_binding else '✗'}")
    
    # Overall result
    all_tests_passed = (setup_success and after_setup_binding and rule_exists and 
                       status_success and cleanup_success)
    
    print()
    if all_tests_passed:
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("❌ Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
