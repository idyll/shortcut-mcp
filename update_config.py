#!/usr/bin/env python
"""Update Claude Desktop config with Shortcut API token from .env file."""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load the token from .env file
load_dotenv()
token = os.getenv("SHORTCUT_API_TOKEN")

if token == "your_token_here":
    print("Error: Please update your .env file with your actual Shortcut API token first.")
    print("You can get your API token from https://app.shortcut.com/settings/account/api-tokens")
    exit(1)

# Get the Claude Desktop config path
if os.name == "posix":  # macOS
    config_path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
elif os.name == "nt":  # Windows
    config_path = os.path.join(os.environ["APPDATA"], "Claude", "claude_desktop_config.json")
else:
    print("Unsupported platform. Claude Desktop is only available on macOS and Windows.")
    exit(1)

# Read the current config
try:
    with open(config_path, "r") as f:
        config = json.load(f)
except FileNotFoundError:
    print(f"Error: Claude Desktop config file not found at {config_path}")
    exit(1)

# Update the token
if "mcpServers" in config and "shortcut" in config["mcpServers"]:
    config["mcpServers"]["shortcut"]["env"]["SHORTCUT_API_TOKEN"] = token
    print(f"Updated Shortcut API token in Claude Desktop config.")
else:
    print("Error: Shortcut MCP server not found in Claude Desktop config.")
    print("Please run 'shortcut-mcp setup' first.")
    exit(1)

# Write the updated config
with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print(f"Claude Desktop config updated successfully at {config_path}")
print("You can now use the Shortcut MCP server in Claude Desktop!") 
