#!/usr/bin/env python3

"""
Firewall Manager for Tempest UDP Broadcasts
===========================================

Standalone firewall management utility for opening UDP ports for Tempest weather station broadcasts.
This script can be used independently or as part of a Docker container.

Usage:
    python3 firewall_manager.py --port 50222 --action setup
    python3 firewall_manager.py --port 50222 --action cleanup
    python3 firewall_manager.py --port 50222 --action status
"""

import argparse
import atexit
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from typing import Tuple


class FirewallManager:
    """Manages iptables rules for UDP broadcast reception"""
    
    def __init__(self, port=50222):
        self.port = port
        self.rule_added = False
        self.is_linux = platform.system().lower() == 'linux'
        self.rule_comment = f"tempest-calibration-{port}"
        self.skip_setup = False
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals to ensure cleanup"""
        print(f"\nReceived signal {signum}, cleaning up firewall rules...")
        self.cleanup()
        sys.exit(0)
    
    def _run_command(self, cmd, check_output=False):
        """Run a shell command with error handling"""
        try:
            if check_output:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
            else:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                return result.returncode == 0, "", result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def _check_root_or_sudo(self):
        """Check if we're running as root or have sudo privileges"""
        import os
        
        # Check if running as root
        if os.geteuid() == 0:
            return True, True  # (has_privileges, is_root)
        
        # Not root, check sudo
        success, _, _ = self._run_command("sudo -n true")
        return success, False  # (has_privileges, is_root)
    
    def _rule_exists(self):
        """Check if our iptables rule already exists"""
        if not self.is_linux:
            return False
        
        # Check if we're root or need sudo
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        cmd = f"{sudo_prefix}iptables -C INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment} 2>/dev/null"
        success, _, _ = self._run_command(cmd)
        return success
    
    def add_rule(self):
        """Add iptables rule to allow UDP broadcasts"""
        if not self.is_linux:
            print("Firewall management only supported on Linux systems")
            return True
        
        if self._rule_exists():
            print(f"Firewall rule for UDP port {self.port} already exists")
            return True
        
        # Check privileges and determine command prefix
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            print("Warning: No root/sudo privileges. You may need to manually allow UDP port 50222:")
            print(f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT")
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        privilege_type = "root" if is_root else "sudo"
        
        print(f"Adding iptables rule to allow UDP broadcasts on port {self.port} (using {privilege_type})...")
        cmd = f"{sudo_prefix}iptables -I INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment}"
        success, _, error = self._run_command(cmd)
        
        if success:
            self.rule_added = True
            print(f"✓ Firewall rule added successfully")
            return True
        else:
            print(f"✗ Failed to add firewall rule: {error}")
            manual_cmd = f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT"
            print(f"Manual command: {manual_cmd}")
            return False
    
    def remove_rule(self):
        """Remove the iptables rule we added"""
        if not self.is_linux or not self.rule_added:
            return True
        
        if not self._rule_exists():
            print(f"Firewall rule for UDP port {self.port} not found")
            self.rule_added = False
            return True
        
        # Check privileges and determine command prefix
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            print(f"Warning: No root/sudo privileges to remove firewall rule")
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        privilege_type = "root" if is_root else "sudo"
        
        print(f"Removing iptables rule for UDP port {self.port} (using {privilege_type})...")
        cmd = f"{sudo_prefix}iptables -D INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment}"
        success, _, error = self._run_command(cmd)
        
        if success:
            self.rule_added = False
            print(f"✓ Firewall rule removed successfully")
            return True
        else:
            print(f"✗ Failed to remove firewall rule: {error}")
            manual_cmd = f"iptables -D INPUT -p udp --dport {self.port} -j ACCEPT"
            print(f"Manual cleanup: {manual_cmd}")
            return False
    
    def cleanup(self):
        """Clean up firewall rules on exit"""
        if self.rule_added:
            self.remove_rule()
    
    def check_port_status(self):
        """Check if the UDP port is accessible"""
        print(f"Checking UDP port {self.port} accessibility...")
        
        # Try to bind to the port to see if it's available
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(("0.0.0.0", self.port))
            test_sock.close()
            print(f"✓ UDP port {self.port} is accessible")
            return True
        except Exception as e:
            print(f"✗ UDP port {self.port} binding failed: {e}")
            return False
    
    def setup_firewall(self):
        """Setup firewall rules and check port accessibility"""
        print("Setting up firewall for Tempest UDP broadcasts...")
        
        # Check if we're on Linux
        if not self.is_linux:
            print(f"Running on {platform.system()}, skipping iptables configuration")
            return self.check_port_status()
        
        # Check current firewall status
        if self._rule_exists():
            print(f"✓ Firewall rule for UDP port {self.port} already exists")
        else:
            # Try to add the rule
            if not self.add_rule():
                print("⚠️  Could not configure firewall automatically")
                print("If you experience connectivity issues, manually run:")
                print(f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT")
        
        # Test port accessibility
        return self.check_port_status()
    
    def get_status(self):
        """Get current firewall status"""
        print(f"Firewall status for UDP port {self.port}:")
        
        if not self.is_linux:
            print(f"Running on {platform.system()}, iptables not available")
            return self.check_port_status()
        
        if self._rule_exists():
            print(f"✓ Firewall rule exists")
        else:
            print(f"✗ Firewall rule does not exist")
        
        return self.check_port_status()


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Firewall manager for Tempest UDP broadcasts"
    )
    parser.add_argument(
        "--port", 
        type=int,
        default=50222, 
        help="UDP port to manage (default: 50222)"
    )
    parser.add_argument(
        "--action",
        choices=["setup", "cleanup", "status"],
        default="setup",
        help="Action to perform (default: setup)"
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait N seconds after setup before exiting (useful for containers)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()
    
    print("🔥 Firewall Manager for Tempest UDP Broadcasts")
    print("=" * 50)
    print(f"Port: {args.port}")
    print(f"Action: {args.action}")
    print(f"Platform: {platform.system()}")
    print("")
    
    # Initialize firewall manager
    firewall_manager = FirewallManager(port=args.port)
    
    try:
        if args.action == "setup":
            success = firewall_manager.setup_firewall()
            if success:
                print("\n✅ Firewall setup completed successfully")
            else:
                print("\n❌ Firewall setup failed")
                sys.exit(1)
                
        elif args.action == "cleanup":
            success = firewall_manager.remove_rule()
            if success:
                print("\n✅ Firewall cleanup completed successfully")
            else:
                print("\n❌ Firewall cleanup failed")
                sys.exit(1)
                
        elif args.action == "status":
            success = firewall_manager.get_status()
            if success:
                print("\n✅ Port is accessible")
            else:
                print("\n❌ Port is not accessible")
                sys.exit(1)
        
        # Wait if requested (useful for containers that need to keep running)
        if args.wait > 0:
            print(f"\n⏳ Waiting {args.wait} seconds before exiting...")
            time.sleep(args.wait)
            
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
