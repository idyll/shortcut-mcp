#!/usr/bin/env python3
"""Test the update-story tool with team_id and epic_id parameters."""

import os
import re

# Print the test plan
print("This test script will verify the update-story handler with team_id and epic_id parameters.")
print("It will check the server.py file directly to verify our changes.")
print()

# Path to the server.py file
server_path = os.path.join("src", "shortcut_mcp", "server.py")

if not os.path.exists(server_path):
    print(f"Error: {server_path} not found")
    exit(1)

# Read the server.py file
with open(server_path, "r") as f:
    server_code = f.read()

print("=== Checking update-story tool ===")

# Check for the team_id parameter in the update-story tool schema
team_id_pattern = r'"team_id":\s*{\s*"type":\s*"number"'
team_id_match = re.search(team_id_pattern, server_code)

if team_id_match:
    print("✅ team_id parameter is present in the schema")
else:
    print("❌ team_id parameter is missing from the schema")

# Check for the team_name parameter in the update-story tool schema
team_name_pattern = r'"team_name":\s*{\s*"type":\s*"string"'
team_name_match = re.search(team_name_pattern, server_code)

if team_name_match:
    print("✅ team_name parameter is present in the schema")
else:
    print("❌ team_name parameter is missing from the schema")

# Check for the epic_id parameter in the update-story tool schema
epic_id_pattern = r'"epic_id":\s*{\s*"type":\s*"number"'
epic_id_match = re.search(epic_id_pattern, server_code)

if epic_id_match:
    print("✅ epic_id parameter is present in the schema")
else:
    print("❌ epic_id parameter is missing from the schema")

# Check for the epic_name parameter in the update-story tool schema
epic_name_pattern = r'"epic_name":\s*{\s*"type":\s*"string"'
epic_name_match = re.search(epic_name_pattern, server_code)

if epic_name_match:
    print("✅ epic_name parameter is present in the schema")
else:
    print("❌ epic_name parameter is missing from the schema")

# Check for the list-teams tool
list_teams_pattern = r'name="list-teams"'
list_teams_match = re.search(list_teams_pattern, server_code)

if list_teams_match:
    print("✅ list-teams tool is present")
else:
    print("❌ list-teams tool is missing")

# Check for the team_id handling in the update-story handler
team_id_handler_pattern = r'if team_id := arguments\.get\("team_id"\):'
team_id_handler_match = re.search(team_id_handler_pattern, server_code)

if team_id_handler_match:
    print("✅ team_id handling is present in the update-story handler")
else:
    print("❌ team_id handling is missing from the update-story handler")

# Check for the team_name handling in the update-story handler
team_name_handler_pattern = r'if team_name := arguments\.get\("team_name"\):'
team_name_handler_match = re.search(team_name_handler_pattern, server_code)

if team_name_handler_match:
    print("✅ team_name handling is present in the update-story handler")
else:
    print("❌ team_name handling is missing from the update-story handler")

# Check for the group_id assignment in the update-story handler
group_id_pattern = r'story_data\["group_id"\] = (?:team_id|found_team_id)'
group_id_match = re.search(group_id_pattern, server_code)

if group_id_match:
    print("✅ group_id assignment is present in the update-story handler")
else:
    print("❌ group_id assignment is missing from the update-story handler")

print("\n=== Checking list-workflows and list-projects tools ===")

# Check for the list-workflows tool with proper properties
list_workflows_pattern = r'name="list-workflows".*?inputSchema=\{.*?"properties":\s*\{.*?# Add any optional parameters.*?\}'
list_workflows_match = re.search(list_workflows_pattern, server_code, re.DOTALL)

if list_workflows_match:
    print("✅ list-workflows tool has proper properties")
else:
    print("❌ list-workflows tool is missing or has improper properties")

# Check for the list-projects tool with proper properties
list_projects_pattern = r'name="list-projects".*?inputSchema=\{.*?"properties":\s*\{.*?# Add any optional parameters.*?\}'
list_projects_match = re.search(list_projects_pattern, server_code, re.DOTALL)

if list_projects_match:
    print("✅ list-projects tool has proper properties")
else:
    print("❌ list-projects tool is missing or has improper properties")

# Check for the None arguments handling in the list-workflows handler
list_workflows_handler_pattern = r'elif name == "list-workflows":\s*# Ensure arguments is a dictionary even if None was passed\s*if arguments is None:\s*arguments = \{\}'
list_workflows_handler_match = re.search(list_workflows_handler_pattern, server_code, re.DOTALL)

if list_workflows_handler_match:
    print("✅ list-workflows handler has proper None arguments handling")
else:
    print("❌ list-workflows handler is missing proper None arguments handling")

# Check for the None arguments handling in the list-projects handler
list_projects_handler_pattern = r'elif name == "list-projects":\s*# Ensure arguments is a dictionary even if None was passed\s*if arguments is None:\s*arguments = \{\}'
list_projects_handler_match = re.search(list_projects_handler_pattern, server_code, re.DOTALL)

if list_projects_handler_match:
    print("✅ list-projects handler has proper None arguments handling")
else:
    print("❌ list-projects handler is missing proper None arguments handling")

print("\nTest completed!") 
