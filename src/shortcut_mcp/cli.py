#!/usr/bin/env python
"""CLI interface for shortcut-mcp."""

import argparse
import asyncio
import os
import sys
import json
import platform

from . import server

def get_config_path():
    """Get Claude Desktop config path based on platform."""
    if platform.system() == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    elif platform.system() == "Windows":
        return os.path.join(os.environ["APPDATA"], "Claude", "claude_desktop_config.json")
    else:
        print("Unsupported platform. Claude Desktop is only available on macOS and Windows.")
        sys.exit(1)

def setup_claude_desktop(token=None):
    """Set up the MCP server in Claude Desktop."""
    config_path = get_config_path()
    
    # Get token if not provided
    if not token:
        token = os.environ.get("SHORTCUT_API_TOKEN")
        if not token:
            token = input("Enter your Shortcut API token: ")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    # Load existing config or create new one
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                config = {}
    else:
        config = {}
    
    # Ensure mcpServers key exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    
    # Add our server config
    config["mcpServers"]["shortcut"] = {
        "command": sys.executable,
        "args": ["-m", "shortcut_mcp", "start"],
        "env": {
            "SHORTCUT_API_TOKEN": token
        }
    }
    
    # Save the updated config
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Shortcut MCP server added to Claude Desktop configuration at {config_path}")
    print("You can now use the Shortcut MCP server in Claude Desktop!")

def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        description="Shortcut MCP Server - Interact with Shortcut from Claude"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Start command
    start_parser = subparsers.add_parser("start", help="Start the MCP server")
    start_parser.add_argument(
        "--token", help="Shortcut API token (or set SHORTCUT_API_TOKEN env var)"
    )
    
    # Setup command
    setup_parser = subparsers.add_parser(
        "setup", help="Set up the MCP server in Claude Desktop"
    )
    setup_parser.add_argument(
        "--token", help="Shortcut API token (or set SHORTCUT_API_TOKEN env var)"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Default to start if no command specified
    if not args.command:
        args.command = "start"
    
    # Handle token
    if args.command in ["start", "setup"] and hasattr(args, "token") and args.token:
        os.environ["SHORTCUT_API_TOKEN"] = args.token
    
    # Execute command
    if args.command == "start":
        asyncio.run(server.main())
    elif args.command == "setup":
        setup_claude_desktop(args.token if hasattr(args, "token") else None)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main() 
