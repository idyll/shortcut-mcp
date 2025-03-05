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
    
    # Safety check: Only allow GET and POST methods
    if method not in ["GET", "POST"]:
        raise ValueError(f"Method {method} is not allowed for safety reasons. Only GET and POST are permitted.")
    
    # Safety check: POST requests are only allowed for creation endpoints and search endpoints
    if method == "POST" and not any(endpoint.endswith(x) for x in ["stories", "epics", "objectives", "search", "stories/search"]):
        raise ValueError(f"POST requests are only allowed for creation and search endpoints, not for {endpoint}")
    
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
    # Check if we already have this state in the cache
    if workflow_state_id in workflow_states_cache:
        return workflow_states_cache[workflow_state_id]
    
    # Otherwise, fetch all workflows and find the state
    workflows = await make_shortcut_request("GET", "workflows")
    
    for workflow in workflows:
        for state in workflow.get("states", []):
            if state["id"] == workflow_state_id:
                # Cache the result for future use
                workflow_states_cache[workflow_state_id] = state["name"]
                return state["name"]
    
    return "Unknown"

async def get_member_name(member_id: str) -> str:
    """Get the name of a member by ID"""
    # Check if we already have this member in the cache
    if member_id in members_cache:
        return members_cache[member_id]
    
    # Otherwise, fetch all members and find the member
    members = await make_shortcut_request("GET", "members")
    
    for member in members:
        if member.get("id") == member_id:
            # Cache the result for future use
            members_cache[member_id] = member.get("name", "Unknown")
            return member.get("name", "Unknown")
    
    return "Unknown"

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
    
    # Get owner and requestor information
    owners = story.get("owner_ids", [])
    owner_names = []
    for owner_id in owners:
        owner_name = await get_member_name(owner_id)
        owner_names.append(owner_name)
    
    owner_info = f"Owners: {', '.join(owner_names)}" if owner_names else "No owners assigned"
    
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
                },
                "required": ["name", "description", "story_type", "project_id"],
            },
        ),
        types.Tool(
            name="list-projects",
            description="List all projects in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="list-workflows",
            description="List all workflows and their states",
            inputSchema={
                "type": "object",
                "properties": {},
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
    ]

@shortcut_server.server.call_tool()
async def handle_call_tool(
    name: str,
    arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests"""
    if not arguments:
        raise ValueError("Missing arguments")

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
            story_data = {
                "name": arguments["name"],
                "description": arguments["description"],
                "story_type": arguments["story_type"],
                "project_id": arguments["project_id"],
            }

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

        elif name == "list-workflows":
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
            objective_data = {
                "name": arguments["name"],
                "description": arguments["description"],
                "status": arguments["status"],
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
            params = {}
            if status := arguments.get("status"):
                params["status"] = status

            epics = await make_shortcut_request("GET", "epics", params=params)
            
            if not epics:
                return [types.TextContent(
                    type="text",
                    text="No epics found"
                )]

            formatted_epics = [format_epic(epic) for epic in epics]
            return [types.TextContent(
                type="text",
                text="Epics:\n\n" + "\n".join(formatted_epics)
            )]

        elif name == "create-epic":
            epic_data = {
                "name": arguments["name"],
                "description": arguments["description"],
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
            
            # Search for stories
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

        else:
            raise ValueError(f"Unknown tool: {name}")

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
