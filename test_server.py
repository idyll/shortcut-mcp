#!/usr/bin/env python
"""Test the Shortcut MCP server by making a direct request to it."""

import httpx
import json
import os
from dotenv import load_dotenv

# Load the token from .env file
load_dotenv()
token = os.getenv("SHORTCUT_API_TOKEN")

if token == "your_token_here":
    print("Error: Please update your .env file with your actual Shortcut API token first.")
    print("You can get your API token from https://app.shortcut.com/settings/account/api-tokens")
    exit(1)

# Set up the request
url = "http://localhost:8000/call-tool"
headers = {"Content-Type": "application/json"}
payload = {
    "tool": "list-tools",
    "args": {}
}

# Make the request
try:
    response = httpx.post(url, json=payload, headers=headers, timeout=10.0)
    response.raise_for_status()
    result = response.json()
    
    print("Server response:")
    print(json.dumps(result, indent=2))
    
    print("\nServer is working correctly!")
    print("You can now use the Shortcut MCP server in Claude Desktop.")
    print("Try asking Claude questions like:")
    print("- \"List my stories\"")
    print("- \"List stories in the In Development state\"")
    print("- \"List stories in the Ready for Review state assigned to [your name]\"")
    print("- \"Search for stories with the keyword 'bug'\"")
    
except httpx.HTTPStatusError as e:
    print(f"Error: HTTP request failed with status code {e.response.status_code}")
    print(e.response.text)
except httpx.RequestError as e:
    print(f"Error: Could not connect to the server. Make sure it's running.")
    print(f"Details: {e}")
except Exception as e:
    print(f"Error: {e}") 
