import asyncio
import os
from typing import Any, Optional, Dict
import httpx
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
import mcp.server.stdio
from dotenv import load_dotenv
import re

# Load environment variables from .env file
load_dotenv()

# Constants
API_BASE_URL = "https://api.app.shortcut.com/api/v3"
SHORTCUT_API_TOKEN = os.getenv("SHORTCUT_API_TOKEN")

# Cache for workflow states
workflow_states_cache: Dict[int, str] = {}

# Cache for member information
members_cache = {}

# Create a ShortcutServer class to maintain state
class ShortcutServer:
    def __init__(self, name: str):
        self.server = Server(name)
        self.authenticated_user = None
    
    async def initialize(self):
        """Initialize the server and authenticate with Shortcut"""
        try:
            # Try to get current user info to verify authentication
            user_info = await make_shortcut_request("GET", "member")
            self.authenticated_user = user_info
        except Exception as e:
            self.authenticated_user = None
            print(f"Warning: Authentication failed - {str(e)}")

# Initialize with:
shortcut_server = ShortcutServer("shortcut")

# Helper functions
async def make_shortcut_request(
    method: str,
    endpoint: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None
) -> dict[str, Any]:
    """Make an authenticated request to the Shortcut API with safety checks"""
    
    # Safety check: Only allow GET, POST, and PUT methods
    if method not in ["GET", "POST", "PUT"]:
        raise ValueError(f"Method {method} is not allowed for safety reasons. Only GET, POST, and PUT are permitted.")
    
    # Safety check: POST requests are only allowed for creation endpoints and search endpoints
    if method == "POST" and not any(endpoint.endswith(x) for x in ["stories", "epics", "objectives", "search", "stories/search"]):
        raise ValueError(f"POST requests are only allowed for creation and search endpoints, not for {endpoint}")
    
    # Safety check: PUT requests are only allowed for updating stories
    if method == "PUT" and not endpoint.startswith("stories/"):
        raise ValueError(f"PUT requests are only allowed for updating stories, not for {endpoint}")
    
    if not SHORTCUT_API_TOKEN:
        raise ValueError("SHORTCUT_API_TOKEN environment variable not set")

    headers = {
        "Content-Type": "application/json",
        "Shortcut-Token": SHORTCUT_API_TOKEN
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=method,
                url=f"{API_BASE_URL}/{endpoint}",
                headers=headers,
                json=json,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise httpx.HTTPError(f"HTTP error occurred: {str(e)} - Status code: {e.response.status_code}")
    except httpx.RequestError as e:
        raise ValueError(f"Request error occurred: {str(e)}")
    except Exception as e:
        raise ValueError(f"An unexpected error occurred: {str(e)}")

async def get_workflow_state_name(workflow_state_id: int) -> str:
    """Get the name of a workflow state by ID"""
    # Check cache first
    if workflow_state_id in workflow_states_cache:
        return workflow_states_cache[workflow_state_id]
    
    # If not in cache, fetch from API
    workflows = await make_shortcut_request("GET", "workflows")
    for workflow in workflows:
        for state in workflow.get("states", []):
            if state.get("id") == workflow_state_id:
                # Cache the result for future use
                workflow_states_cache[workflow_state_id] = state.get("name", "Unknown")
                return state.get("name", "Unknown")
    
    return "Unknown"

async def get_member_name(member_id: str) -> str:
    """Get the name of a member by ID"""
    # Check cache first
    if member_id in members_cache:
        return members_cache[member_id]
    
    # If not in cache, fetch from API
    try:
        member = await make_shortcut_request("GET", f"members/{member_id}")
        name = member.get("name", member.get("mention_name", "Unknown"))
        # Cache the result for future use
        members_cache[member_id] = name
        return name
    except Exception:
        return "Unknown"

async def find_workflow_state_id(workflow_state_name: str) -> tuple[int, str]:
    """Find a workflow state ID by name, with support for partial matching.
    
    Returns:
        tuple: (workflow_state_id, actual_state_name) or (None, None) if not found
    """
    workflows = await make_shortcut_request("GET", "workflows")
    
    # First try exact match (case-insensitive)
    for workflow in workflows:
        for state in workflow.get("states", []):
            if state["name"].lower() == workflow_state_name.lower():
                workflow_state_id = state["id"]
                # Cache the state name
                workflow_states_cache[state["id"]] = state["name"]
                return workflow_state_id, state["name"]
    
    # If no exact match, try partial match
    for workflow in workflows:
        for state in workflow.get("states", []):
            if workflow_state_name.lower() in state["name"].lower():
                workflow_state_id = state["id"]
                # Cache the state name
                workflow_states_cache[state["id"]] = state["name"]
                return workflow_state_id, state["name"]
    
    return None, None

async def find_epic_by_name(epic_name: str) -> tuple[int, str]:
    """Find an epic by name, with support for partial matching.
    
    Returns:
        tuple: (epic_id, actual_epic_name) or (None, None) if not found
    """
    epics = await make_shortcut_request("GET", "epics")
    
    # First try exact match (case-insensitive)
    for epic in epics:
        if epic.get("name", "").lower() == epic_name.lower():
            return epic.get("id"), epic.get("name")
    
    # If no exact match, try partial match
    for epic in epics:
        if epic_name.lower() in epic.get("name", "").lower():
            return epic.get("id"), epic.get("name")
    
    return None, None

def format_objective(objective: dict) -> str:
    """Format an objective into a readable string"""
    return (
        f"Objective: {objective['name']}\n"
        f"Status: {objective.get('status', 'Unknown')}\n"
        f"Description: {objective.get('description', 'No description')}\n"
        "---"
    )

def format_epic(epic: dict) -> str:
    """Format an epic into a readable string"""
    return (
        f"Epic: {epic['name']}\n"
        f"Status: {epic.get('status', 'Unknown')}\n"
        f"Description: {epic.get('description', 'No description')}\n"
        f"URL: {epic.get('app_url', '')}\n"
        "---"
    )

async def format_story(story: dict) -> str:
    """Format a story into a readable string"""
    # Get the workflow state name asynchronously if needed
    workflow_state_id = story.get("workflow_state_id")
    workflow_state_name = "Unknown"
    
    # If we have the workflow state ID, try to get the name from cache
    if workflow_state_id is not None and workflow_state_id in workflow_states_cache:
        workflow_state_name = workflow_states_cache[workflow_state_id]
    elif workflow_state_id is not None:
        workflow_state_name = await get_workflow_state_name(workflow_state_id)
    
    # Get owner and requestor information
    owners = story.get("owner_ids", [])
    owner_names = []
    for owner_id in owners:
        if owner_id:  # Only process non-empty owner IDs
            owner_name = await get_member_name(owner_id)
            owner_names.append(owner_name)
    
    owner_info = f"Owners: {', '.join(owner_names)}" if owner_names else "No owners assigned"
    
    # Get team information
    team_id = story.get("group_id")
    team_info = "No team assigned"
    if team_id:
        try:
            teams = await make_shortcut_request("GET", "groups")
            for team in teams:
                if team.get("id") == team_id:
                    team_info = f"Team: {team.get('name', 'Unknown')}"
                    break
        except Exception:
            pass
    
    # Get epic information
    epic_id = story.get("epic_id")
    epic_info = "No epic assigned"
    if epic_id:
        try:
            epic = await make_shortcut_request("GET", f"epics/{epic_id}")
            epic_info = f"Epic: {epic.get('name', 'Unknown')} (ID: {epic_id})"
        except Exception:
            pass
    
    requestor_id = story.get("requested_by_id")
    requestor_name = "Unknown"
    if requestor_id:
        requestor_name = await get_member_name(requestor_id)
    
    requestor_info = f"Requested by: {requestor_name}" if requestor_id else "No requestor information"
    
    # Get creation and update times
    created_at = story.get("created_at", "Unknown")
    updated_at = story.get("updated_at", "Unknown")
    
    return (
        f"Story {story['id']}: {story['name']}\n"
        f"Status: {workflow_state_name}\n"
        f"Type: {story.get('story_type', 'Unknown')}\n"
        f"{owner_info}\n"
        f"{team_info}\n"
        f"{epic_info}\n"
        f"{requestor_info}\n"
        f"Created: {created_at}\n"
        f"Updated: {updated_at}\n"
        f"Description: {story.get('description', 'No description')}\n"
        f"URL: {story.get('app_url', '')}\n"
        "---"
    )

@shortcut_server.server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools for the Shortcut MCP server."""
    # Add user info to tool descriptions if authenticated
    user_info = ""
    if shortcut_server.authenticated_user:
        user_name = shortcut_server.authenticated_user.get("name", "Unknown")
        user_info = f" (authenticated as {user_name})"
    
    return [
        types.Tool(
            name="search-stories",
            description=f"Search for stories in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g., 'is:story state:\"In Development\" owner:me')"
                    },
                    "owner_name": {
                        "type": "string",
                        "description": "Filter by owner name (person assigned to the story)"
                    },
                    "requestor_name": {
                        "type": "string",
                        "description": "Filter by requestor name (person who requested the story)"
                    },
                    "state_name": {
                        "type": "string",
                        "description": "Filter by workflow state name (e.g., 'In Development', 'Ready for Review')"
                    },
                    "created_after": {
                        "type": "string",
                        "description": "Filter stories created after this date (YYYY-MM-DD)"
                    },
                    "created_before": {
                        "type": "string",
                        "description": "Filter stories created before this date (YYYY-MM-DD)"
                    },
                    "updated_after": {
                        "type": "string",
                        "description": "Filter stories updated after this date (YYYY-MM-DD)"
                    },
                    "updated_before": {
                        "type": "string",
                        "description": "Filter stories updated before this date (YYYY-MM-DD)"
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived stories (default: false)"
                    }
                }
            }
        ),
        types.Tool(
            name="list-archived-stories",
            description="List only archived stories",
            inputSchema={
                "type": "object",
                "properties": {
                    "owner_name": {
                        "type": "string",
                        "description": "Filter by owner name. Leave empty to see all archived stories."
                    },
                    "state_name": {
                        "type": "string",
                        "description": "Filter by workflow state name. Leave empty to see all states."
                    }
                }
            }
        ),
        types.Tool(
            name="list-my-archived-stories",
            description="List only archived stories assigned to you",
            inputSchema={
                "type": "object",
                "properties": {
                    "state_name": {
                        "type": "string",
                        "description": "Filter by workflow state name. Leave empty to see all states."
                    }
                }
            }
        ),
        types.Tool(
            name="list-my-stories",
            description="List stories assigned to you",
            inputSchema={
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "description": "Filter by workflow state (e.g., 'In Development', 'Ready for Review'). Leave empty for all states."
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived stories (default: false)"
                    }
                }
            }
        ),
        types.Tool(
            name="list-stories-by-state-name",
            description="List stories by workflow state name",
            inputSchema={
                "type": "object",
                "properties": {
                    "state_name": {
                        "type": "string",
                        "description": "Workflow state name (e.g., 'In Development', 'Ready for Review')"
                    },
                    "owner_name": {
                        "type": "string",
                        "description": "Filter by owner name. Leave empty for all owners."
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived stories (default: false)"
                    }
                },
                "required": ["state_name"]
            }
        ),
        types.Tool(
            name="create-story",
            description=f"Create a new story in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Story title",
                    },
                    "description": {
                        "type": "string",
                        "description": "Story description",
                    },
                    "story_type": {
                        "type": "string",
                        "description": "Story type (feature, bug, chore)",
                        "enum": ["feature", "bug", "chore"],
                    },
                    "project_id": {
                        "type": "number",
                        "description": "Project ID to create the story in",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Project name to create the story in (alternative to project_id)",
                    },
                    "epic_id": {
                        "type": "number",
                        "description": "Epic ID to associate with the story",
                    },
                    "epic_name": {
                        "type": "string",
                        "description": "Epic name to associate with the story (alternative to epic_id)",
                    },
                    "workflow_state_name": {
                        "type": "string",
                        "description": "Workflow state name (e.g., 'Backlog', 'In Development'). Defaults to 'Backlog' if not specified.",
                    },
                },
                "required": ["name", "description", "story_type"],
            },
        ),
        types.Tool(
            name="list-projects",
            description="List all projects in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {
                    # Add any optional parameters here if needed in the future
                },
                # No required parameters
            },
        ),
        types.Tool(
            name="list-teams",
            description="List all teams in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {
                    # Add any optional parameters here if needed in the future
                },
                # No required parameters
            },
        ),
        types.Tool(
            name="list-workflows",
            description="List all workflows and their states",
            inputSchema={
                "type": "object",
                "properties": {
                    # Add any optional parameters here if needed in the future
                },
                # No required parameters
            },
        ),
        types.Tool(
            name="list-objectives",
            description="List objectives in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status (active, draft, closed)",
                        "enum": ["active", "draft", "closed"],
                    },
                },
            },
        ),
        types.Tool(
            name="create-objective",
            description=f"Create a new objective in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Objective name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Objective description",
                    },
                    "status": {
                        "type": "string",
                        "description": "Objective status",
                        "enum": ["active", "draft", "closed"],
                    },
                },
                "required": ["name", "description", "status"],
            },
        ),
        types.Tool(
            name="list-epics",
            description="List epics in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status (to do, in progress, done)",
                        "enum": ["to do", "in progress", "done"],
                    },
                },
            },
        ),
        types.Tool(
            name="create-epic",
            description=f"Create a new epic in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Epic name",
                    },
                    "description": {
                        "type": "string",
                        "description": "Epic description",
                    },
                    "milestone_id": {
                        "type": "number",
                        "description": "Optional milestone ID to associate with the epic",
                    },
                },
                "required": ["name", "description"],
            },
        ),
        types.Tool(
            name="list-stories-by-status",
            description="List stories by workflow state ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "workflow_state_id": {
                        "type": "string",
                        "description": "Workflow state ID",
                    },
                    "owner_name": {
                        "type": "string",
                        "description": "Filter by owner name",
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Include archived stories (default: false)"
                    }
                },
                "required": ["workflow_state_id"],
            },
        ),
        types.Tool(
            name="update-story",
            description=f"Update an existing story in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "story_id": {
                        "type": "string",
                        "description": "Story ID to update",
                    },
                    "name": {
                        "type": "string",
                        "description": "New story title",
                    },
                    "description": {
                        "type": "string",
                        "description": "New story description",
                    },
                    "story_type": {
                        "type": "string",
                        "description": "New story type (feature, bug, chore)",
                        "enum": ["feature", "bug", "chore"],
                    },
                    "workflow_state_name": {
                        "type": "string",
                        "description": "New workflow state name (e.g., 'Backlog', 'In Development')",
                    },
                    "project_id": {
                        "type": "number",
                        "description": "New project ID for the story",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "New project name for the story (alternative to project_id)",
                    },
                    "epic_id": {
                        "type": "number",
                        "description": "New epic ID for the story",
                    },
                    "epic_name": {
                        "type": "string",
                        "description": "New epic name for the story",
                    },
                    "team_id": {
                        "type": "number",
                        "description": "New team ID for the story (group_id in Shortcut API)",
                    },
                    "team_name": {
                        "type": "string",
                        "description": "New team name for the story (alternative to team_id)",
                    },
                },
                "required": ["story_id"],
            },
        ),
        types.Tool(
            name="update-story-status",
            description=f"Update a story's status in Shortcut{user_info}",
            inputSchema={
                "type": "object",
                "properties": {
                    "story_id": {
                        "type": "string",
                        "description": "Story ID to update",
                    },
                    "status": {
                        "type": "string",
                        "description": "New status for the story (e.g., 'Backlog', 'In Development')",
                    },
                },
                "required": ["story_id", "status"],
            },
        ),
    ]

@shortcut_server.server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests"""
    # Initialize arguments as an empty dictionary if it's None
    if arguments is None:
        arguments = {}

    try:
        if name == "search-stories":
            query = arguments.get("query", "")
            owner_name = arguments.get("owner_name")
            requestor_name = arguments.get("requestor_name")
            state_name = arguments.get("state_name")
            created_after = arguments.get("created_after")
            created_before = arguments.get("created_before")
            updated_after = arguments.get("updated_after")
            updated_before = arguments.get("updated_before")
            include_archived = arguments.get("include_archived", False)
            
            # Parse the query string if provided
            if query:
                # Extract parameters from the query string
                
                # Extract state
                state_match = re.search(r'state:["\'"]?([^"\'\s]+)["\'"]?', query)
                if state_match and not state_name:
                    state_name = state_match.group(1)
                
                # Extract owner
                owner_match = re.search(r'owner:([^\s]+)', query)
                if owner_match and not owner_name:
                    owner_value = owner_match.group(1)
                    if owner_value.lower() == 'me':
                        # Use the authenticated user
                        if shortcut_server.authenticated_user:
                            owner_name = shortcut_server.authenticated_user.get("name")
                    else:
                        owner_name = owner_value
                
                # Extract created_by
                created_by_match = re.search(r'created_by:([^\s]+)', query)
                if created_by_match:
                    created_by_value = created_by_match.group(1)
                    if created_by_value.lower() == 'me':
                        # Use the authenticated user as requestor
                        if shortcut_server.authenticated_user:
                            requestor_name = shortcut_server.authenticated_user.get("name")
                    else:
                        requestor_name = created_by_value
                
                # Extract archived status
                archived_match = re.search(r'archived:(true|false)', query, re.IGNORECASE)
                if archived_match:
                    include_archived = archived_match.group(1).lower() == 'true'
            
            search_json = {}
            filter_description = []
            
            # Set archived status (default to false unless explicitly included)
            search_json["archived"] = include_archived
            if include_archived:
                filter_description.append("including archived stories")
            else:
                filter_description.append("excluding archived stories")
            
            # Handle owner filter
            if owner_name:
                # Get all members to find the owner ID
                members = await make_shortcut_request("GET", "members")
                owner_id = None
                for member in members:
                    if member.get("name", "").lower() == owner_name.lower() or member.get("mention_name", "").lower() == owner_name.lower():
                        owner_id = member.get("id")
                        break
                
                if owner_id:
                    search_json["owner_ids"] = [owner_id]
                    filter_description.append(f"owned by {owner_name}")
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find member with name '{owner_name}'"
                    )]
            
            # Handle requestor filter
            if requestor_name:
                # Get all members to find the requestor ID
                members = await make_shortcut_request("GET", "members")
                requestor_id = None
                for member in members:
                    if member.get("name", "").lower() == requestor_name.lower() or member.get("mention_name", "").lower() == requestor_name.lower():
                        requestor_id = member.get("id")
                        break
                
                if requestor_id:
                    search_json["requested_by_id"] = requestor_id
                    filter_description.append(f"requested by {requestor_name}")
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find member with name '{requestor_name}'"
                    )]
            
            # Handle workflow state filter
            if state_name:
                # Get all workflows to find the workflow state ID
                workflows = await make_shortcut_request("GET", "workflows")
                workflow_state_id = None
                for workflow in workflows:
                    for state in workflow.get("states", []):
                        if state["name"].lower() == state_name.lower():
                            workflow_state_id = state["id"]
                            # Cache the state name
                            workflow_states_cache[state["id"]] = state["name"]
                            break
                    if workflow_state_id:
                        break
                
                if workflow_state_id:
                    search_json["workflow_state_id"] = workflow_state_id
                    filter_description.append(f"in state '{state_name}'")
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find workflow state with name '{state_name}'"
                    )]
            
            # Handle time-based filters
            if created_after:
                search_json["created_at_start"] = f"{created_after}T00:00:00Z"
                filter_description.append(f"created after {created_after}")
            
            if created_before:
                search_json["created_at_end"] = f"{created_before}T23:59:59Z"
                filter_description.append(f"created before {created_before}")
            
            if updated_after:
                search_json["updated_at_start"] = f"{updated_after}T00:00:00Z"
                filter_description.append(f"updated after {updated_after}")
            
            if updated_before:
                search_json["updated_at_end"] = f"{updated_before}T23:59:59Z"
                filter_description.append(f"updated before {updated_before}")
            
            # If no filters were provided, return an error
            if not search_json:
                return [types.TextContent(
                    type="text",
                    text="Please provide at least one search filter"
                )]
            
            # Search for stories
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                filter_text = " and ".join(filter_description)
                return [types.TextContent(
                    type="text",
                    text=f"No stories found {filter_text}"
                )]
            
            # Collect all unique workflow state IDs from the stories
            workflow_state_ids = set()
            for story in stories:
                if story.get("workflow_state_id"):
                    workflow_state_ids.add(story.get("workflow_state_id"))
            
            # Populate the cache with workflow state names
            for state_id in workflow_state_ids:
                if state_id not in workflow_states_cache:
                    state_name = await get_workflow_state_name(state_id)
                    workflow_states_cache[state_id] = state_name
            
            formatted_stories = [await format_story(story) for story in stories]
            filter_text = " and ".join(filter_description)
            return [types.TextContent(
                type="text",
                text=f"Found stories {filter_text}:\n\n" + "\n".join(formatted_stories)
            )]
        
        elif name == "advanced-search-stories":
            # Remove this handler since we've merged it with search-stories
            return [types.TextContent(
                type="text",
                text="This tool has been deprecated. Please use 'search-stories' instead."
            )]

        elif name == "create-story":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            project_id = arguments.get("project_id")
            project_name = arguments.get("project_name")
            epic_id = arguments.get("epic_id")
            epic_name = arguments.get("epic_name")
            
            # If neither project_id nor project_name is provided, list projects and ask user to select one
            if not project_id and not project_name:
                projects = await make_shortcut_request("GET", "projects")
                
                formatted_projects = []
                for project in projects:
                    formatted_projects.append(
                        f"Project ID: {project['id']}\n"
                        f"Name: {project['name']}\n"
                        f"Description: {project.get('description', 'No description')}\n"
                        "---"
                    )

                return [types.TextContent(
                    type="text",
                    text="Please provide either a project ID or project name from the list below and try again:\n\n" + 
                         "\n".join(formatted_projects)
                )]
            
            # If project_name is provided, find the corresponding project_id
            if project_name and not project_id:
                projects = await make_shortcut_request("GET", "projects")
                for project in projects:
                    if project.get("name", "").lower() == project_name.lower():
                        project_id = project.get("id")
                        break
                
                if not project_id:
                    # If we couldn't find the project, list available projects
                    formatted_projects = []
                    for project in projects:
                        formatted_projects.append(
                            f"Project ID: {project['id']}\n"
                            f"Name: {project['name']}\n"
                            f"Description: {project.get('description', 'No description')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find project with name '{project_name}'. Available projects:\n\n" + 
                             "\n".join(formatted_projects)
                    )]
            
            # If epic_name is provided, find the corresponding epic_id
            if epic_name and not epic_id:
                epic_id, actual_epic_name = await find_epic_by_name(epic_name)
                
                if not epic_id:
                    # If we couldn't find the epic, list available epics
                    epics = await make_shortcut_request("GET", "epics")
                    formatted_epics = []
                    for epic in epics:
                        formatted_epics.append(
                            f"Epic ID: {epic['id']}\n"
                            f"Name: {epic['name']}\n"
                            f"Status: {epic.get('status', 'Unknown')}\n"
                            f"Description: {epic.get('description', 'No description')}\n"
                            f"URL: {epic.get('app_url', '')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find epic with name '{epic_name}'. Available epics:\n\n" + 
                             "\n".join(formatted_epics)
                    )]
            
            # Get the workflow state ID for "Backlog" or the specified state
            workflow_state_name = arguments.get("workflow_state_name", "Backlog")
            workflow_state_id, actual_state_name = await find_workflow_state_id(workflow_state_name)
            
            if not workflow_state_id:
                # If we couldn't find the specified state, list available states
                workflows = await make_shortcut_request("GET", "workflows")
                formatted_workflows = []
                for workflow in workflows:
                    states = [
                        f"- {state['name']} (ID: {state['id']})"
                        for state in workflow.get("states", [])
                    ]
                    
                    formatted_workflows.append(
                        f"Workflow: {workflow['name']}\n"
                        f"States:\n" + "\n".join(states) + "\n"
                        "---"
                    )
                
                return [types.TextContent(
                    type="text",
                    text=f"Could not find workflow state '{workflow_state_name}'. Available states:\n\n" + 
                         "\n".join(formatted_workflows)
                )]
            
            # Prepare story data
            story_data = {
                "name": arguments["name"],
                "description": arguments["description"],
                "story_type": arguments["story_type"],
                "project_id": project_id,
                "workflow_state_id": workflow_state_id,
            }
            
            # Add epic_id if provided
            if epic_id:
                try:
                    # Convert epic_id to integer if it's a string
                    if isinstance(epic_id, str):
                        epic_id = int(epic_id)
                    story_data["epic_id"] = epic_id
                except ValueError:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid epic_id: {epic_id}. Must be a valid integer."
                    )]
            
            # Handle epic_name if provided
            if epic_name := arguments.get("epic_name"):
                # Get all epics to find the epic ID
                epics = await make_shortcut_request("GET", "epics")
                found_epic_id = None
                for epic in epics:
                    if epic.get("name", "").lower() == epic_name.lower():
                        found_epic_id = epic.get("id")
                        break
                
                if found_epic_id:
                    story_data["epic_id"] = found_epic_id
                else:
                    # If we couldn't find the epic, list available epics
                    formatted_epics = []
                    for epic in epics:
                        formatted_epics.append(
                            f"Epic ID: {epic['id']}\n"
                            f"Name: {epic['name']}\n"
                            f"Description: {epic.get('description', 'No description')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find epic with name '{epic_name}'. Available epics:\n\n" + 
                             "\n".join(formatted_epics)
                    )]
            
            # Handle team_id if provided
            if team_id := arguments.get("team_id"):
                try:
                    # Convert team_id to integer if it's a string
                    if isinstance(team_id, str):
                        team_id = int(team_id)
                    story_data["group_id"] = team_id  # Shortcut API uses group_id for teams
                except ValueError:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid team_id: {team_id}. Must be a valid integer."
                    )]
                
            # Handle team_name if provided
            if team_name := arguments.get("team_name"):
                # Get all teams to find the team ID
                teams = await make_shortcut_request("GET", "groups")
                found_team_id = None
                for team in teams:
                    if team.get("name", "").lower() == team_name.lower():
                        found_team_id = team.get("id")
                        break
                
                if found_team_id:
                    story_data["group_id"] = found_team_id  # Shortcut API uses group_id for teams
                else:
                    # If we couldn't find the team, list available teams
                    formatted_teams = []
                    for team in teams:
                        formatted_teams.append(
                            f"Team ID: {team['id']}\n"
                            f"Name: {team['name']}\n"
                            f"Description: {team.get('description', 'No description')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find team with name '{team_name}'. Available teams:\n\n" + 
                             "\n".join(formatted_teams)
                    )]
            
            # Assign to authenticated user if available
            if shortcut_server.authenticated_user:
                user_id = shortcut_server.authenticated_user.get("id")
                if user_id:
                    story_data["owner_ids"] = [user_id]
                
                # Assign to the user's team if available
                team_ids = shortcut_server.authenticated_user.get("group_ids", [])
                if team_ids and len(team_ids) > 0:
                    story_data["group_id"] = team_ids[0]  # Assign to the first team if multiple

            new_story = await make_shortcut_request(
                "POST",
                "stories",
                json=story_data
            )

            return [types.TextContent(
                type="text",
                text=f"Created new story:\n\n{await format_story(new_story)}"
            )]

        elif name == "list-projects":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            projects = await make_shortcut_request("GET", "projects")
            
            formatted_projects = []
            for project in projects:
                formatted_projects.append(
                    f"Project ID: {project['id']}\n"
                    f"Name: {project['name']}\n"
                    f"Description: {project.get('description', 'No description')}\n"
                    "---"
                )

            return [types.TextContent(
                type="text",
                text="Available projects:\n\n" + "\n".join(formatted_projects)
            )]

        elif name == "list-teams":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            teams = await make_shortcut_request("GET", "groups")
            
            formatted_teams = []
            for team in teams:
                formatted_teams.append(
                    f"Team ID: {team['id']}\n"
                    f"Name: {team['name']}\n"
                    f"Description: {team.get('description', 'No description')}\n"
                    "---"
                )

            return [types.TextContent(
                type="text",
                text="Available teams:\n\n" + "\n".join(formatted_teams)
            )]

        elif name == "list-workflows":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            workflows = await make_shortcut_request("GET", "workflows")
            
            formatted_workflows = []
            for workflow in workflows:
                states = [
                    f"- {state['name']} (ID: {state['id']})"
                    for state in workflow.get("states", [])
                ]
                
                formatted_workflows.append(
                    f"Workflow: {workflow['name']}\n"
                    f"States:\n" + "\n".join(states) + "\n"
                    "---"
                )

            return [types.TextContent(
                type="text",
                text="Available workflows and states:\n\n" + "\n".join(formatted_workflows)
            )]

        elif name == "list-objectives":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            params = {}
            if status := arguments.get("status"):
                params["status"] = status

            objectives = await make_shortcut_request("GET", "objectives", params=params)
            
            if not objectives:
                return [types.TextContent(
                    type="text",
                    text="No objectives found"
                )]

            formatted_objectives = [format_objective(obj) for obj in objectives]
            return [types.TextContent(
                type="text",
                text="Objectives:\n\n" + "\n".join(formatted_objectives)
            )]

        elif name == "create-objective":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            objective_data = {
                "name": arguments.get("name"),
                "description": arguments.get("description"),
                "status": arguments.get("status"),
            }

            new_objective = await make_shortcut_request(
                "POST",
                "objectives",
                json=objective_data
            )

            return [types.TextContent(
                type="text",
                text=f"Created new objective:\n\n{format_objective(new_objective)}"
            )]

        elif name == "list-epics":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            params = {}
            if status := arguments.get("status"):
                params["status"] = status

            epics = await make_shortcut_request("GET", "epics", params=params)
            
            if not epics:
                return [types.TextContent(
                    type="text",
                    text="No epics found"
                )]

            formatted_epics = []
            for epic in epics:
                formatted_epics.append(
                    f"Epic ID: {epic['id']}\n"
                    f"Name: {epic['name']}\n"
                    f"Status: {epic.get('status', 'Unknown')}\n"
                    f"Description: {epic.get('description', 'No description')}\n"
                    f"URL: {epic.get('app_url', '')}\n"
                    "---"
                )
            
            return [types.TextContent(
                type="text",
                text="Epics:\n\n" + "\n".join(formatted_epics)
            )]

        elif name == "create-epic":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            epic_data = {
                "name": arguments.get("name"),
                "description": arguments.get("description"),
            }

            if milestone_id := arguments.get("milestone_id"):
                epic_data["milestone_id"] = milestone_id

            new_epic = await make_shortcut_request(
                "POST",
                "epics",
                json=epic_data
            )

            return [types.TextContent(
                type="text",
                text=f"Created new epic:\n\n{format_epic(new_epic)}"
            )]

        elif name == "list-stories-by-status":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            workflow_state_id = arguments.get("workflow_state_id")
            owner_name = arguments.get("owner_name")
            include_archived = arguments.get("include_archived", False)
            
            # Get owner ID if owner_name is provided
            owner_id = None
            if owner_name:
                # Get all members to find the owner ID
                members = await make_shortcut_request("GET", "members")
                for member in members:
                    if member.get("name", "").lower() == owner_name.lower() or member.get("mention_name", "").lower() == owner_name.lower():
                        owner_id = member.get("id")
                        break
                
                if not owner_id:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find member with name '{owner_name}'"
                    )]
            
            # Prepare search parameters
            search_json = {
                "workflow_state_id": int(workflow_state_id),
                "archived": include_archived
            }
            if owner_id:
                search_json["owner_ids"] = [owner_id]
            
            # Use POST to search stories with workflow_state_id
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                owner_msg = f" assigned to {owner_name}" if owner_name else ""
                archived_msg = " (including archived)" if include_archived else ""
                return [types.TextContent(
                    type="text",
                    text=f"No stories found with the specified status{owner_msg}{archived_msg}"
                )]

            # Get the workflow state name and cache it
            state_name = await get_workflow_state_name(int(workflow_state_id))
            workflow_states_cache[int(workflow_state_id)] = state_name
            
            formatted_stories = [await format_story(story) for story in stories]
            owner_msg = f" assigned to {owner_name}" if owner_name else ""
            archived_msg = " (including archived)" if include_archived else ""
            return [types.TextContent(
                type="text",
                text=f"Stories in the '{state_name}' state{owner_msg}{archived_msg}:\n\n" + "\n".join(formatted_stories)
            )]

        elif name == "list-my-stories":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            state_name = arguments.get("state")
            include_archived = arguments.get("include_archived", False)
            
            # Get the authenticated user's ID
            if not shortcut_server.authenticated_user:
                return [types.TextContent(
                    type="text",
                    text="You need to be authenticated to use this tool"
                )]
            
            user_id = shortcut_server.authenticated_user.get("id")
            if not user_id:
                return [types.TextContent(
                    type="text",
                    text="Could not determine your user ID"
                )]
            
            # First, get all workflows to find the workflow state ID if a state name was provided
            workflow_state_id = None
            if state_name:
                workflows = await make_shortcut_request("GET", "workflows")
                for workflow in workflows:
                    for state in workflow.get("states", []):
                        if state["name"].lower() == state_name.lower():
                            workflow_state_id = state["id"]
                            # Cache the state name
                            workflow_states_cache[state["id"]] = state["name"]
                            break
                    if workflow_state_id:
                        break
            
            # Prepare the search parameters
            search_json = {
                "owner_ids": [user_id],
                "archived": include_archived
            }
            if workflow_state_id:
                search_json["workflow_state_id"] = workflow_state_id
            
            # Search for stories assigned to the user
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                state_msg = f" in the '{state_name}' state" if state_name else ""
                archived_msg = " (including archived)" if include_archived else ""
                return [types.TextContent(
                    type="text",
                    text=f"No stories assigned to you{state_msg}{archived_msg}"
                )]
            
            # Collect all unique workflow state IDs from the stories
            workflow_state_ids = set()
            for story in stories:
                if story.get("workflow_state_id"):
                    workflow_state_ids.add(story.get("workflow_state_id"))
            
            # Populate the cache with workflow state names
            for state_id in workflow_state_ids:
                if state_id not in workflow_states_cache:
                    state_name_from_id = await get_workflow_state_name(state_id)
                    workflow_states_cache[state_id] = state_name_from_id
            
            formatted_stories = [await format_story(story) for story in stories]
            state_msg = f" in the '{state_name}' state" if state_name else ""
            archived_msg = " (including archived)" if include_archived else ""
            return [types.TextContent(
                type="text",
                text=f"Stories assigned to you{state_msg}{archived_msg}:\n\n" + "\n".join(formatted_stories)
            )]

        elif name == "list-stories-by-state-name":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            state_name = arguments.get("state_name")
            owner_name = arguments.get("owner_name")
            include_archived = arguments.get("include_archived", False)
            
            if not state_name:
                return [types.TextContent(
                    type="text",
                    text="Please provide a workflow state name"
                )]
            
            # First, get all workflows to find the workflow state ID
            workflow_state_id = None
            workflows = await make_shortcut_request("GET", "workflows")
            for workflow in workflows:
                for state in workflow.get("states", []):
                    if state["name"].lower() == state_name.lower():
                        workflow_state_id = state["id"]
                        # Cache the state name
                        workflow_states_cache[state["id"]] = state["name"]
                        break
                if workflow_state_id:
                    break
            
            if not workflow_state_id:
                return [types.TextContent(
                    type="text",
                    text=f"Could not find workflow state with name '{state_name}'"
                )]
            
            # Prepare the search parameters
            search_json = {
                "workflow_state_id": workflow_state_id,
                "archived": include_archived
            }
            
            # If owner name is provided, find the owner ID
            if owner_name:
                # Get all members to find the owner ID
                members = await make_shortcut_request("GET", "members")
                owner_id = None
                for member in members:
                    if member.get("name", "").lower() == owner_name.lower() or member.get("mention_name", "").lower() == owner_name.lower():
                        owner_id = member.get("id")
                        break
                
                if owner_id:
                    search_json["owner_ids"] = [owner_id]
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find member with name '{owner_name}'"
                    )]
            
            # Search for stories with the specified workflow state
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                owner_msg = f" assigned to {owner_name}" if owner_name else ""
                archived_msg = " (including archived)" if include_archived else ""
                return [types.TextContent(
                    type="text",
                    text=f"No stories found in the '{state_name}' state{owner_msg}{archived_msg}"
                )]
            
            # Collect all unique workflow state IDs from the stories
            workflow_state_ids = set()
            for story in stories:
                if story.get("workflow_state_id"):
                    workflow_state_ids.add(story.get("workflow_state_id"))
            
            # Populate the cache with workflow state names
            for state_id in workflow_state_ids:
                if state_id not in workflow_states_cache:
                    state_name_from_id = await get_workflow_state_name(state_id)
                    workflow_states_cache[state_id] = state_name_from_id
            
            formatted_stories = [await format_story(story) for story in stories]
            owner_msg = f" assigned to {owner_name}" if owner_name else ""
            archived_msg = " (including archived)" if include_archived else ""
            return [types.TextContent(
                type="text",
                text=f"Stories in the '{state_name}' state{owner_msg}{archived_msg}:\n\n" + "\n".join(formatted_stories)
            )]

        elif name == "list-archived-stories":
            owner_name = arguments.get("owner_name")
            state_name = arguments.get("state_name")
            
            # Prepare the search parameters - always set archived to true
            search_json = {
                "archived": True
            }
            
            # If owner name is provided, find the owner ID
            if owner_name:
                # Get all members to find the owner ID
                members = await make_shortcut_request("GET", "members")
                owner_id = None
                for member in members:
                    if member.get("name", "").lower() == owner_name.lower() or member.get("mention_name", "").lower() == owner_name.lower():
                        owner_id = member.get("id")
                        break
                
                if owner_id:
                    search_json["owner_ids"] = [owner_id]
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find member with name '{owner_name}'"
                    )]
            
            # If state name is provided, find the workflow state ID
            if state_name:
                # Get all workflows to find the workflow state ID
                workflows = await make_shortcut_request("GET", "workflows")
                workflow_state_id = None
                for workflow in workflows:
                    for state in workflow.get("states", []):
                        if state["name"].lower() == state_name.lower():
                            workflow_state_id = state["id"]
                            # Cache the state name
                            workflow_states_cache[state["id"]] = state["name"]
                            break
                    if workflow_state_id:
                        break
                
                if workflow_state_id:
                    search_json["workflow_state_id"] = workflow_state_id
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find workflow state with name '{state_name}'"
                    )]
            
            # Search for archived stories
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                owner_msg = f" assigned to {owner_name}" if owner_name else ""
                state_msg = f" in the '{state_name}' state" if state_name else ""
                return [types.TextContent(
                    type="text",
                    text=f"No archived stories found{owner_msg}{state_msg}"
                )]
            
            # Collect all unique workflow state IDs from the stories
            workflow_state_ids = set()
            for story in stories:
                if story.get("workflow_state_id"):
                    workflow_state_ids.add(story.get("workflow_state_id"))
            
            # Populate the cache with workflow state names
            for state_id in workflow_state_ids:
                if state_id not in workflow_states_cache:
                    state_name_from_id = await get_workflow_state_name(state_id)
                    workflow_states_cache[state_id] = state_name_from_id
            
            formatted_stories = [await format_story(story) for story in stories]
            owner_msg = f" assigned to {owner_name}" if owner_name else ""
            state_msg = f" in the '{state_name}' state" if state_name else ""
            return [types.TextContent(
                type="text",
                text=f"Archived stories{owner_msg}{state_msg}:\n\n" + "\n".join(formatted_stories)
            )]

        elif name == "list-my-archived-stories":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            state_name = arguments.get("state_name")
            
            # Get the authenticated user's ID
            if not shortcut_server.authenticated_user:
                return [types.TextContent(
                    type="text",
                    text="You need to be authenticated to use this tool"
                )]
            
            user_id = shortcut_server.authenticated_user.get("id")
            if not user_id:
                return [types.TextContent(
                    type="text",
                    text="Could not determine your user ID"
                )]
            
            # Prepare the search parameters - always set archived to true
            search_json = {
                "owner_ids": [user_id],
                "archived": True
            }
            
            # If state name is provided, find the workflow state ID
            if state_name:
                # Get all workflows to find the workflow state ID
                workflows = await make_shortcut_request("GET", "workflows")
                workflow_state_id = None
                for workflow in workflows:
                    for state in workflow.get("states", []):
                        if state["name"].lower() == state_name.lower():
                            workflow_state_id = state["id"]
                            # Cache the state name
                            workflow_states_cache[state["id"]] = state["name"]
                            break
                    if workflow_state_id:
                        break
                
                if workflow_state_id:
                    search_json["workflow_state_id"] = workflow_state_id
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find workflow state with name '{state_name}'"
                    )]
            
            # Search for archived stories assigned to the user
            stories = await make_shortcut_request(
                "POST",
                "stories/search",
                json=search_json
            )
            
            if not stories:
                state_msg = f" in the '{state_name}' state" if state_name else ""
                return [types.TextContent(
                    type="text",
                    text=f"No archived stories assigned to you{state_msg}"
                )]
            
            # Collect all unique workflow state IDs from the stories
            workflow_state_ids = set()
            for story in stories:
                if story.get("workflow_state_id"):
                    workflow_state_ids.add(story.get("workflow_state_id"))
            
            # Populate the cache with workflow state names
            for state_id in workflow_state_ids:
                if state_id not in workflow_states_cache:
                    state_name_from_id = await get_workflow_state_name(state_id)
                    workflow_states_cache[state_id] = state_name_from_id
            
            formatted_stories = [await format_story(story) for story in stories]
            state_msg = f" in the '{state_name}' state" if state_name else ""
            return [types.TextContent(
                type="text",
                text=f"Archived stories assigned to you{state_msg}:\n\n" + "\n".join(formatted_stories)
            )]

        elif name == "update-story":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            story_id = arguments.get("story_id")
            
            if not story_id:
                return [types.TextContent(
                    type="text",
                    text="Please provide a story ID"
                )]
            
            # First, get the current story to update only the fields that are provided
            try:
                current_story = await make_shortcut_request("GET", f"stories/{story_id}")
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=f"Error retrieving story {story_id}: {str(e)}"
                )]
            
            # Prepare story data with only the fields that are provided
            story_data = {}
            
            if name := arguments.get("name"):
                story_data["name"] = name
                
            if description := arguments.get("description"):
                story_data["description"] = description
                
            if story_type := arguments.get("story_type"):
                story_data["story_type"] = story_type
                
            if project_id := arguments.get("project_id"):
                try:
                    # Convert project_id to integer if it's a string
                    if isinstance(project_id, str):
                        project_id = int(project_id)
                    story_data["project_id"] = project_id
                except ValueError:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid project_id: {project_id}. Must be a valid integer."
                    )]
                
            # Handle epic_id if provided
            if epic_id := arguments.get("epic_id"):
                try:
                    # Convert epic_id to integer if it's a string
                    if isinstance(epic_id, str):
                        epic_id = int(epic_id)
                    story_data["epic_id"] = epic_id
                except ValueError:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid epic_id: {epic_id}. Must be a valid integer."
                    )]
                
            # Handle epic_name if provided
            if epic_name := arguments.get("epic_name"):
                # Get all epics to find the epic ID
                epics = await make_shortcut_request("GET", "epics")
                found_epic_id = None
                for epic in epics:
                    if epic.get("name", "").lower() == epic_name.lower():
                        found_epic_id = epic.get("id")
                        break
                
                if found_epic_id:
                    story_data["epic_id"] = found_epic_id
                else:
                    # If we couldn't find the epic, list available epics
                    formatted_epics = []
                    for epic in epics:
                        formatted_epics.append(
                            f"Epic ID: {epic['id']}\n"
                            f"Name: {epic['name']}\n"
                            f"Description: {epic.get('description', 'No description')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find epic with name '{epic_name}'. Available epics:\n\n" + 
                             "\n".join(formatted_epics)
                    )]
            
            # Handle team_id if provided
            if team_id := arguments.get("team_id"):
                try:
                    # Convert team_id to integer if it's a string
                    if isinstance(team_id, str):
                        team_id = int(team_id)
                    story_data["group_id"] = team_id  # Shortcut API uses group_id for teams
                except ValueError:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid team_id: {team_id}. Must be a valid integer."
                    )]
                
            # Handle team_name if provided
            if team_name := arguments.get("team_name"):
                # Get all teams to find the team ID
                teams = await make_shortcut_request("GET", "groups")
                found_team_id = None
                for team in teams:
                    if team.get("name", "").lower() == team_name.lower():
                        found_team_id = team.get("id")
                        break
                
                if found_team_id:
                    story_data["group_id"] = found_team_id  # Shortcut API uses group_id for teams
                else:
                    # If we couldn't find the team, list available teams
                    formatted_teams = []
                    for team in teams:
                        formatted_teams.append(
                            f"Team ID: {team['id']}\n"
                            f"Name: {team['name']}\n"
                            f"Description: {team.get('description', 'No description')}\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find team with name '{team_name}'. Available teams:\n\n" + 
                             "\n".join(formatted_teams)
                    )]
            
            # Handle workflow state name if provided
            if workflow_state_name := arguments.get("workflow_state_name"):
                # Get the workflow state ID for the specified state
                workflow_state_id, actual_state_name = await find_workflow_state_id(workflow_state_name)
                
                if workflow_state_id:
                    story_data["workflow_state_id"] = workflow_state_id
                else:
                    # If we couldn't find the state, list available states
                    workflows = await make_shortcut_request("GET", "workflows")
                    formatted_workflows = []
                    for workflow in workflows:
                        states = [
                            f"- {state['name']} (ID: {state['id']})"
                            for state in workflow.get("states", [])
                        ]
                        
                        formatted_workflows.append(
                            f"Workflow: {workflow['name']}\n"
                            f"States:\n" + "\n".join(states) + "\n"
                            "---"
                        )
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Could not find workflow state with name '{workflow_state_name}'. Available states:\n\n" + 
                             "\n".join(formatted_workflows)
                    )]
            
            if not story_data:
                return [types.TextContent(
                    type="text",
                    text="No fields to update were provided"
                )]
            
            # Update the story
            try:
                updated_story = await make_shortcut_request(
                    "PUT",
                    f"stories/{story_id}",
                    json=story_data
                )
                
                return [types.TextContent(
                    type="text",
                    text=f"Updated story:\n\n{await format_story(updated_story)}"
                )]
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=f"Error updating story: {str(e)}"
                )]

        elif name == "update-story-status":
            # Ensure arguments is a dictionary even if None was passed
            if arguments is None:
                arguments = {}
                
            story_id = arguments.get("story_id")
            status = arguments.get("status")
            
            if not story_id:
                return [types.TextContent(
                    type="text",
                    text="Please provide a story ID"
                )]
            
            if not status:
                return [types.TextContent(
                    type="text",
                    text="Please provide a new status for the story"
                )]
            
            # First, get the current story to update only the fields that are provided
            try:
                current_story = await make_shortcut_request("GET", f"stories/{story_id}")
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=f"Error retrieving story {story_id}: {str(e)}"
                )]
            
            # Find the workflow state ID for the provided status
            workflow_state_id, actual_state_name = await find_workflow_state_id(status)
            
            if not workflow_state_id:
                # If we couldn't find the state, list available states
                workflows = await make_shortcut_request("GET", "workflows")
                formatted_workflows = []
                for workflow in workflows:
                    states = [
                        f"- {state['name']} (ID: {state['id']})"
                        for state in workflow.get("states", [])
                    ]
                    
                    formatted_workflows.append(
                        f"Workflow: {workflow['name']}\n"
                        f"States:\n" + "\n".join(states) + "\n"
                        "---"
                    )
                
                return [types.TextContent(
                    type="text",
                    text=f"Could not find workflow state with name '{status}'. Available states:\n\n" + 
                         "\n".join(formatted_workflows)
                )]
            
            # Prepare story data with only the workflow state ID
            story_data = {
                "workflow_state_id": workflow_state_id
            }
            
            # Update the story
            try:
                updated_story = await make_shortcut_request(
                    "PUT",
                    f"stories/{story_id}",
                    json=story_data
                )
                
                return [types.TextContent(
                    type="text",
                    text=f"Updated story status to '{actual_state_name}':\n\n{await format_story(updated_story)}"
                )]
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=f"Error updating story status: {str(e)}"
                )]

        else:
            return [types.TextContent(
                type="text",
                text=f"Unknown tool: {name}"
            )]

    except httpx.HTTPError as e:
        return [types.TextContent(
            type="text",
            text=f"API request failed: {str(e)}"
        )]

async def main():
    """Run the server using stdin/stdout streams"""
    # Initialize server and authenticate
    await shortcut_server.initialize()
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await shortcut_server.server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="shortcut",
                server_version="0.2.0",
                capabilities=shortcut_server.server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
