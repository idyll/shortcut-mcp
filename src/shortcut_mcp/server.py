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
import random
import time
from contextlib import asynccontextmanager
import sys

# Load environment variables from .env file
load_dotenv()

# Constants
API_BASE_URL = "https://api.app.shortcut.com/api/v3"
SHORTCUT_API_TOKEN = os.getenv("SHORTCUT_API_TOKEN")

# Custom exceptions for better error handling
class ShortcutAPIError(Exception):
    """Base exception for Shortcut API errors"""
    pass

class ShortcutAuthError(ShortcutAPIError):
    """Authentication errors"""
    pass
    
class ShortcutRateLimitError(ShortcutAPIError):
    """Rate limit exceeded errors"""
    pass
    
class ShortcutServerError(ShortcutAPIError):
    """Server-side errors"""
    pass

class ShortcutTimeoutError(ShortcutAPIError):
    """Timeout errors"""
    pass

class ShortcutConnectionError(ShortcutAPIError):
    """Connection errors"""
    pass

# Cache for workflow states
workflow_states_cache: Dict[int, str] = {}

# Cache for member information
members_cache = {}

# HTTP client pool
http_client = None

@asynccontextmanager
async def get_http_client():
    """Get or create an HTTP client from the pool"""
    global http_client
    
    # Create a new client if one doesn't exist
    if http_client is None:
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=30.0)
        http_client = httpx.AsyncClient(limits=limits, timeout=timeout)
    
    try:
        yield http_client
    except Exception as e:
        # If there's a connection error, reset the client
        if isinstance(e, (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.PoolTimeout)):
            await http_client.aclose()
            http_client = None
        raise

async def cleanup_http_client():
    """Close the HTTP client when shutting down"""
    global http_client
    if http_client is not None:
        await http_client.aclose()
        http_client = None

# Create a ShortcutServer class to maintain state
class ShortcutServer:
    def __init__(self, name: str):
        self.server = Server(name)
        self.authenticated_user = None
        self.last_activity_time = time.time()
    
    async def initialize(self):
        """Initialize the server and authenticate with Shortcut"""
        try:
            # Try to get current user info to verify authentication
            user_info = await make_shortcut_request("GET", "member")
            self.authenticated_user = user_info
        except Exception as e:
            self.authenticated_user = None
            print(f"Warning: Authentication failed - {str(e)}")
    
    def update_activity(self):
        """Update the last activity timestamp"""
        self.last_activity_time = time.time()
    
    def get_inactivity_time(self):
        """Get the time since the last activity in seconds"""
        return time.time() - self.last_activity_time

# Initialize with:
shortcut_server = ShortcutServer("shortcut")

# Helper functions
async def make_shortcut_request(
    method: str,
    endpoint: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    max_retries: int = 3,
    base_timeout: float = 30.0
) -> dict[str, Any]:
    """Make an authenticated request to the Shortcut API with safety checks and retry logic"""
    
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
        raise ShortcutAuthError("SHORTCUT_API_TOKEN environment variable not set")

    headers = {
        "Content-Type": "application/json",
        "Shortcut-Token": SHORTCUT_API_TOKEN
    }

    # Update the server's last activity time
    shortcut_server.update_activity()

    # Implement exponential backoff for retries
    retry_count = 0
    last_exception = None
    
    while retry_count < max_retries:
        try:
            # Use the connection pool
            async with get_http_client() as client:
                response = await client.request(
                    method=method,
                    url=f"{API_BASE_URL}/{endpoint}",
                    headers=headers,
                    json=json,
                    params=params
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.TimeoutException as e:
            last_exception = ShortcutTimeoutError(f"Request timed out: {str(e)}")
            retry_count += 1
            if retry_count < max_retries:
                # Exponential backoff with jitter
                backoff_time = (2 ** retry_count) + (0.1 * random.random())
                print(f"Request timed out. Retrying in {backoff_time:.2f} seconds... (Attempt {retry_count}/{max_retries})")
                await asyncio.sleep(backoff_time)
            
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            
            # Don't retry client errors (4xx) except for 429 (rate limit)
            if status_code == 401:
                raise ShortcutAuthError(f"Authentication failed: {str(e)}")
            elif status_code == 429:
                last_exception = ShortcutRateLimitError(f"Rate limit exceeded: {str(e)}")
                retry_count += 1
                # Get retry-after header or use exponential backoff
                retry_after = int(e.response.headers.get('retry-after', 2 ** retry_count))
                print(f"Rate limited. Retrying in {retry_after} seconds... (Attempt {retry_count}/{max_retries})")
                await asyncio.sleep(retry_after)
            elif 500 <= status_code < 600:
                # Server errors (5xx) should be retried
                last_exception = ShortcutServerError(f"Server error {status_code}: {str(e)}")
                retry_count += 1
                backoff_time = (2 ** retry_count) + (0.1 * random.random())
                print(f"Server error {status_code}. Retrying in {backoff_time:.2f} seconds... (Attempt {retry_count}/{max_retries})")
                await asyncio.sleep(backoff_time)
            else:
                # Client errors should not be retried
                raise ShortcutAPIError(f"HTTP error occurred: {str(e)} - Status code: {status_code}")
                
        except httpx.RequestError as e:
            # Network-related errors should be retried
            last_exception = ShortcutConnectionError(f"Connection error: {str(e)}")
            retry_count += 1
            if retry_count < max_retries:
                backoff_time = (2 ** retry_count) + (0.1 * random.random())
                print(f"Request error. Retrying in {backoff_time:.2f} seconds... (Attempt {retry_count}/{max_retries})")
                await asyncio.sleep(backoff_time)
                
        except Exception as e:
            # Unexpected errors should not be retried
            raise ShortcutAPIError(f"An unexpected error occurred: {str(e)}")
    
    # If we've exhausted all retries
    if last_exception:
        raise last_exception

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
    """Find an epic by name"""
    epics = await make_shortcut_request("GET", "epics")
    
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
    """Format a story into a readable string with optimized async calls"""
    # Prepare all coroutines we need to run in parallel
    tasks = []
    task_types = []
    
    # Get workflow state name if needed
    workflow_state_id = story.get("workflow_state_id")
    if workflow_state_id is not None and workflow_state_id not in workflow_states_cache:
        tasks.append(get_workflow_state_name(workflow_state_id))
        task_types.append("workflow_state")
    
    # Get owner names if needed
    owners = story.get("owner_ids", [])
    for owner_id in owners:
        if owner_id and owner_id not in members_cache:
            tasks.append(get_member_name(owner_id))
            task_types.append(f"owner_{owner_id}")
    
    # Get requestor name if needed
    requestor_id = story.get("requested_by_id")
    if requestor_id and requestor_id not in members_cache:
        tasks.append(get_member_name(requestor_id))
        task_types.append(f"requestor_{requestor_id}")
    
    # Run all tasks in parallel if we have any
    if tasks:
        results = await asyncio.gather(*tasks)
        
        # Process results based on task types
        for i, result in enumerate(results):
            task_type = task_types[i]
            if task_type == "workflow_state":
                # We don't need to do anything here as the cache is updated in get_workflow_state_name
                pass
            elif task_type.startswith("owner_") or task_type.startswith("requestor_"):
                # We don't need to do anything here as the cache is updated in get_member_name
                pass
    
    # Now format the story with all the data we have
    story_id = story.get("id")
    name = story.get("name", "Untitled")
    description = story.get("description", "").strip()
    
    # Get workflow state name from cache
    workflow_state_name = "Unknown"
    if workflow_state_id is not None:
        workflow_state_name = workflow_states_cache.get(workflow_state_id, "Unknown")
    
    # Get owner names from cache
    owner_names = []
    for owner_id in owners:
        if owner_id:
            owner_name = members_cache.get(owner_id, "Unknown")
            owner_names.append(owner_name)
    
    # Get requestor name from cache
    requestor_name = "Unknown"
    if requestor_id:
        requestor_name = members_cache.get(requestor_id, "Unknown")
    
    # Format the story
    formatted_story = f"Story {story_id}: {name}\n"
    formatted_story += f"Status: {workflow_state_name}\n"
    
    if owner_names:
        formatted_story += f"Owners: {', '.join(owner_names)}\n"
    
    formatted_story += f"Requestor: {requestor_name}\n"
    
    if description:
        # Truncate description if it's too long
        if len(description) > 500:
            description = description[:497] + "..."
        formatted_story += f"Description: {description}\n"
    
    return formatted_story

async def format_story_detailed(story: dict) -> str:
    """Format a story into a detailed readable string with all available information"""
    # Prepare all coroutines we need to run in parallel
    tasks = []
    task_types = []
    
    # Get workflow state name if needed
    workflow_state_id = story.get("workflow_state_id")
    if workflow_state_id is not None and workflow_state_id not in workflow_states_cache:
        tasks.append(get_workflow_state_name(workflow_state_id))
        task_types.append("workflow_state")
    
    # Get owner names if needed
    owners = story.get("owner_ids", [])
    for owner_id in owners:
        if owner_id and owner_id not in members_cache:
            tasks.append(get_member_name(owner_id))
            task_types.append(f"owner_{owner_id}")
    
    # Get requestor name if needed
    requestor_id = story.get("requested_by_id")
    if requestor_id and requestor_id not in members_cache:
        tasks.append(get_member_name(requestor_id))
        task_types.append(f"requestor_{requestor_id}")
    
    # Get epic information if needed
    epic_id = story.get("epic_id")
    epic_info = None
    if epic_id:
        tasks.append(make_shortcut_request("GET", f"epics/{epic_id}"))
        task_types.append("epic")
    
    # Run all tasks in parallel if we have any
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results based on task types
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # Skip failed requests
                continue
                
            task_type = task_types[i]
            if task_type == "workflow_state":
                # We don't need to do anything here as the cache is updated in get_workflow_state_name
                pass
            elif task_type.startswith("owner_") or task_type.startswith("requestor_"):
                # We don't need to do anything here as the cache is updated in get_member_name
                pass
            elif task_type == "epic":
                epic_info = result
    
    # Now format the story with all the data we have
    story_id = story.get("id")
    name = story.get("name", "Untitled")
    description = story.get("description", "").strip()
    story_type = story.get("story_type", "Unknown")
    app_url = story.get("app_url", "")
    
    # Get workflow state name from cache
    workflow_state_name = "Unknown"
    if workflow_state_id is not None:
        workflow_state_name = workflow_states_cache.get(workflow_state_id, "Unknown")
    
    # Get owner names from cache
    owner_names = []
    for owner_id in owners:
        if owner_id:
            owner_name = members_cache.get(owner_id, "Unknown")
            owner_names.append(owner_name)
    
    # Get requestor name from cache
    requestor_name = "Unknown"
    if requestor_id:
        requestor_name = members_cache.get(requestor_id, "Unknown")
    
    # Format dates
    created_at = story.get("created_at")
    updated_at = story.get("updated_at")
    
    # Format the story
    formatted_story = f"Story {story_id}: {name}\n"
    formatted_story += f"Status: {workflow_state_name}\n"
    formatted_story += f"Type: {story_type}\n"
    
    if owner_names:
        formatted_story += f"Owners: {', '.join(owner_names)}\n"
    else:
        formatted_story += "Owners: None\n"
    
    formatted_story += f"Requestor: {requestor_name}\n"
    
    # Add epic information if available
    if epic_info:
        formatted_story += f"Epic: {epic_info.get('name', 'Unknown')} (ID: {epic_id})\n"
    
    # Add dates
    if created_at:
        formatted_story += f"Created: {created_at}\n"
    if updated_at:
        formatted_story += f"Updated: {updated_at}\n"
    
    # Add URL
    if app_url:
        formatted_story += f"URL: {app_url}\n"
    
    # Add description
    if description:
        formatted_story += f"\nDescription:\n{description}\n"
    else:
        formatted_story += "\nNo description provided.\n"
    
    return formatted_story

@shortcut_server.server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools"""
    return [
        types.Tool(
            name="search-stories",
            description="Search for stories in Shortcut using powerful search operators",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query with optional operators (e.g., 'SMS type:feature state:\"In Development\" owner:john label:urgent'). Supports operators like type:, state:, owner:, label:, has:attachment, is:blocked, etc."
                    },
                    "owner_name": {
                        "type": "string",
                        "description": "Filter by owner name (person assigned to the story). Will be converted to owner:mention_name in the query."
                    },
                    "requestor_name": {
                        "type": "string",
                        "description": "Filter by requestor name (person who requested the story). Will be converted to requester:mention_name in the query."
                    },
                    "state_name": {
                        "type": "string",
                        "description": "Filter by workflow state name (e.g., 'In Development', 'Ready for Review'). Will be converted to state:\"name\" in the query."
                    },
                    "created_after": {
                        "type": "string",
                        "description": "Filter by creation date (YYYY-MM-DD). Can use 'yesterday' or 'today'. Will be converted to created:date..* in the query."
                    },
                    "created_before": {
                        "type": "string",
                        "description": "Filter by creation date (YYYY-MM-DD). Can use 'yesterday' or 'today'. Will be converted to created:*..date in the query."
                    }
                }
            }
        ),
        types.Tool(
            name="get-story",
            description="Get detailed information about a specific story by ID (fastest way to look up a story)",
            inputSchema={
                "type": "object",
                "properties": {
                    "story_id": {
                        "type": "string",
                        "description": "The ID of the story to retrieve (numeric ID only)"
                    }
                },
                "required": ["story_id"]
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
            description=f"Create a new story in Shortcut",
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
                    "team_id": {
                        "type": "number",
                        "description": "Team ID to create the story in (group_id in Shortcut API)",
                    },
                    "team_name": {
                        "type": "string",
                        "description": "Team name to create the story in (alternative to team_id)",
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
            description="[DEPRECATED] List all projects in Shortcut. Projects have been deprecated by Shortcut, please use teams instead.",
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
            description=f"Create a new objective in Shortcut",
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
            description=f"Create a new epic in Shortcut",
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
            description=f"Update an existing story in Shortcut",
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
            description=f"Update a story's status in Shortcut",
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
        types.Tool(
            name="health-check",
            description="Check the health and connectivity of the Shortcut MCP server",
            inputSchema={
                "type": "object",
                "properties": {}  # No required parameters
            }
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

    # Create a wrapper function to apply timeout to the actual handler
    async def execute_with_timeout(timeout=60.0):
        try:
            # Execute the actual tool handler with a timeout
            return await asyncio.wait_for(
                _handle_tool_implementation(name, arguments),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return [types.TextContent(
                type="text",
                text=f"⏱️ The operation timed out after {timeout} seconds. Please try again with a more specific query or check if the Shortcut API is responding."
            )]
        except ShortcutAuthError as e:
            return [types.TextContent(
                type="text",
                text=f"🔑 Authentication error. Please check your API token. Details: {e}"
            )]
        except ShortcutRateLimitError as e:
            return [types.TextContent(
                type="text",
                text=f"⚠️ Rate limit exceeded. Please try again in a few minutes. Details: {e}"
            )]
        except ShortcutServerError as e:
            return [types.TextContent(
                type="text",
                text=f"⚠️ Shortcut server is experiencing issues. Please try again later. Details: {e}"
            )]
        except ShortcutTimeoutError as e:
            return [types.TextContent(
                type="text",
                text=f"⏱️ Request timed out. The Shortcut API might be slow or unresponsive. Details: {e}"
            )]
        except ShortcutConnectionError as e:
            return [types.TextContent(
                type="text",
                text=f"🌐 Connection error. There might be network issues. Details: {e}"
            )]
        except ShortcutAPIError as e:
            return [types.TextContent(
                type="text",
                text=f"❌ Shortcut API error: {e}"
            )]
        except Exception as e:
            # Log the full exception for debugging
            print(f"Unexpected error in {name}: {type(e).__name__}: {e}", file=sys.stderr)
            return [types.TextContent(
                type="text",
                text=f"An unexpected error occurred. Please try again or simplify your request."
            )]
    
    # Determine an appropriate timeout based on the tool being called
    if name == "search-stories":
        # Search operations can take longer
        timeout = 90.0
    elif name == "get-story":
        # Direct lookups should be fast
        timeout = 30.0
    elif name in ["list-epics", "list-members", "list-stories-by-state-name"]:
        # List operations might take longer
        timeout = 60.0
    else:
        # Default timeout for other operations
        timeout = 45.0
        
    return await execute_with_timeout(timeout)

async def _handle_tool_implementation(
    name: str,
    arguments: dict
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Actual implementation of tool handling logic"""
    try:
        if name == "search-stories":
            query = arguments.get("query", "")
            owner_name = arguments.get("owner_name")
            requestor_name = arguments.get("requestor_name")
            state_name = arguments.get("state_name")
            created_after = arguments.get("created_after")
            created_before = arguments.get("created_before")
            
            # Check if the query looks like a story ID (just numbers)
            if query and re.match(r'^\d+$', query.strip()):
                # This looks like a story ID, suggest using get-story instead
                story_id = query.strip()
                return [types.TextContent(
                    type="text",
                    text=f"It looks like you're searching for a specific story ID ({story_id}). For faster results, please use the get-story tool instead of search-stories."
                )]
            
            # Build a proper Shortcut search query string using their query syntax
            search_query_parts = []
            filter_description = []
            
            # Add the basic text search if provided
            if query:
                # If the query already contains search operators, use it as is
                if any(op in query for op in [":", "is:", "has:", "type:", "state:", "owner:", "label:"]):
                    search_query_parts.append(query)
                    filter_description.append(f"matching '{query}'")
                else:
                    # Otherwise, use it as a general text search
                    search_query_parts.append(query)
                    filter_description.append(f"matching '{query}'")
            
            # Add owner filter if provided
            if owner_name:
                try:
                    # Find the member ID for the given name
                    members = await make_shortcut_request("GET", "members")
                    owner_mention = None
                    
                    for member in members:
                        profile = member.get("profile", {})
                        if owner_name.lower() in profile.get("name", "").lower():
                            # Get the mention name (without @)
                            owner_mention = profile.get("mention_name")
                            break
                    
                    if owner_mention:
                        search_query_parts.append(f"owner:{owner_mention}")
                        filter_description.append(f"owned by '{owner_name}'")
                    else:
                        return [types.TextContent(
                            type="text",
                            text=f"Could not find a member with name '{owner_name}'"
                        )]
                except Exception as e:
                    return [types.TextContent(
                        type="text",
                        text=f"Error finding member: {str(e)}"
                    )]
            
            # Add requestor filter if provided
            if requestor_name:
                try:
                    # Find the member ID for the given name
                    members = await make_shortcut_request("GET", "members")
                    requestor_mention = None
                    
                    for member in members:
                        profile = member.get("profile", {})
                        if requestor_name.lower() in profile.get("name", "").lower():
                            # Get the mention name (without @)
                            requestor_mention = profile.get("mention_name")
                            break
                    
                    if requestor_mention:
                        search_query_parts.append(f"requester:{requestor_mention}")
                        filter_description.append(f"requested by '{requestor_name}'")
                    else:
                        return [types.TextContent(
                            type="text",
                            text=f"Could not find a member with name '{requestor_name}'"
                        )]
                except Exception as e:
                    return [types.TextContent(
                        type="text",
                        text=f"Error finding member: {str(e)}"
                    )]
            
            # Add workflow state filter if provided
            if state_name:
                # Use the state: operator with quotes for multi-word state names
                if " " in state_name:
                    search_query_parts.append(f'state:"{state_name}"')
                else:
                    search_query_parts.append(f'state:{state_name}')
                filter_description.append(f"in state '{state_name}'")
            
            # Add date filters if provided
            if created_after and created_before:
                search_query_parts.append(f"created:{created_after}..{created_before}")
                filter_description.append(f"created between {created_after} and {created_before}")
            elif created_after:
                search_query_parts.append(f"created:{created_after}..*")
                filter_description.append(f"created after {created_after}")
            elif created_before:
                search_query_parts.append(f"created:*..{created_before}")
                filter_description.append(f"created before {created_before}")
            
            # Add is:story to ensure we only get stories
            search_query_parts.append("is:story")
            
            # Combine all query parts with spaces (AND logic)
            search_query = " ".join(search_query_parts)
            
            # Provide feedback that the search is in progress
            progress_message = "Searching for stories"
            if filter_description:
                progress_message += " " + " and ".join(filter_description)
            progress_message += "... (this may take a moment)"
            
            print(progress_message)
            
            try:
                # Try using the GET search endpoint with the proper query syntax
                try:
                    # Set a longer timeout for search operations
                    search_results = await make_shortcut_request(
                        "GET", 
                        "search/stories", 
                        params={"query": search_query},
                        max_retries=2,
                        base_timeout=45.0  # Longer timeout for search
                    )
                    
                    stories = search_results.get("data", [])
                except Exception as e:
                    print(f"GET search failed: {e}")
                    # Fall back to the POST search endpoint with structured parameters
                    search_params = {"archived": False}  # Default to non-archived stories
                    
                    # Try to convert our query to structured parameters
                    if owner_name and "owner_ids" in locals() and owner_id:
                        search_params["owner_ids"] = [owner_id]
                    
                    if requestor_name and "requestor_id" in locals() and requestor_id:
                        search_params["requested_by_id"] = requestor_id
                    
                    if state_name and "workflow_state_id" in locals() and workflow_state_id:
                        search_params["workflow_state_id"] = workflow_state_id
                    
                    if created_after:
                        search_params["created_at_start"] = created_after
                    
                    if created_before:
                        search_params["created_at_end"] = created_before
                    
                    # Add text search if it's a simple query
                    if query and not any(op in query for op in [":", "is:", "has:"]):
                        search_params["text"] = query
                    
                    stories = await make_shortcut_request(
                        "POST", 
                        "stories/search", 
                        json=search_params,
                        max_retries=2,
                        base_timeout=45.0  # Longer timeout for search
                    )
                
                # Format the stories
                if stories:
                    # Limit the number of stories to process to avoid timeouts
                    max_stories = 10
                    if len(stories) > max_stories:
                        truncated_message = f"\n\n(Showing {max_stories} of {len(stories)} stories. Use more specific search criteria to narrow results.)"
                        stories = stories[:max_stories]
                    else:
                        truncated_message = ""
                    
                    # Process stories in parallel for better performance
                    formatted_stories = await asyncio.gather(*[format_story(story) for story in stories])
                    
                    # Join the formatted stories with a separator
                    stories_text = "\n\n".join(formatted_stories)
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Found {len(stories)} stories matching your criteria:{truncated_message}\n\n{stories_text}"
                    )]
                else:
                    return [types.TextContent(
                        type="text",
                        text=f"No stories found matching your criteria. Search query: {search_query}"
                    )]
            except ShortcutTimeoutError:
                return [types.TextContent(
                    type="text",
                    text="⏱️ The search operation timed out. Please try again with more specific search criteria to narrow down the results."
                )]
            except Exception as e:
                # If all search methods fail, try a simpler approach - list all stories and filter client-side
                try:
                    print(f"Search failed, falling back to listing all stories: {e}")
                    # Get all stories and filter client-side
                    all_stories = await make_shortcut_request("GET", "stories", max_retries=2, base_timeout=60.0)
                    
                    # Filter stories based on search criteria
                    filtered_stories = []
                    for story in all_stories:
                        # Apply text search if provided
                        if query and not any(op in query for op in [":", "is:", "has:"]):
                            search_text = query.lower()
                            story_name = story.get("name", "").lower()
                            story_desc = story.get("description", "").lower()
                            
                            if search_text not in story_name and search_text not in story_desc:
                                continue
                        
                        # Apply workflow state filter if provided
                        if state_name:
                            # Get the workflow state name for this story
                            story_state_id = story.get("workflow_state_id")
                            if story_state_id:
                                story_state_name = await get_workflow_state_name(story_state_id)
                                if state_name.lower() not in story_state_name.lower():
                                    continue
                            else:
                                continue
                        
                        # Apply owner filter if provided
                        if owner_name:
                            story_owners = story.get("owner_ids", [])
                            if not story_owners:
                                continue
                                
                            # Check if any of the owners match
                            owner_match = False
                            for owner_id in story_owners:
                                owner_name_from_id = await get_member_name(owner_id)
                                if owner_name.lower() in owner_name_from_id.lower():
                                    owner_match = True
                                    break
                                    
                            if not owner_match:
                                continue
                        
                        # Apply requestor filter if provided
                        if requestor_name:
                            requestor_id = story.get("requested_by_id")
                            if requestor_id:
                                requestor_name_from_id = await get_member_name(requestor_id)
                                if requestor_name.lower() not in requestor_name_from_id.lower():
                                    continue
                            else:
                                continue
                        
                        # Story passed all filters
                        filtered_stories.append(story)
                    
                    # Format the stories
                    if filtered_stories:
                        # Limit the number of stories to process to avoid timeouts
                        max_stories = 10
                        if len(filtered_stories) > max_stories:
                            truncated_message = f"\n\n(Showing {max_stories} of {len(filtered_stories)} stories. Use more specific search criteria to narrow results.)"
                            filtered_stories = filtered_stories[:max_stories]
                        else:
                            truncated_message = ""
                        
                        # Process stories in parallel for better performance
                        formatted_stories = await asyncio.gather(*[format_story(story) for story in filtered_stories])
                        
                        # Join the formatted stories with a separator
                        stories_text = "\n\n".join(formatted_stories)
                        
                        return [types.TextContent(
                            type="text",
                            text=f"Found {len(filtered_stories)} stories matching your criteria (using fallback search):{truncated_message}\n\n{stories_text}"
                        )]
                    else:
                        return [types.TextContent(
                            type="text",
                            text="No stories found matching your criteria (using fallback search)."
                        )]
                except Exception as fallback_error:
                    return [types.TextContent(
                        type="text",
                        text=f"Error searching for stories: {str(e)}\n\nFallback search also failed: {str(fallback_error)}\n\nTry using more specific search criteria or check the Shortcut API status."
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
                
            epic_id = arguments.get("epic_id")
            epic_name = arguments.get("epic_name")
            team_id = arguments.get("team_id")
            team_name = arguments.get("team_name")
            
            # If neither team_id nor team_name is provided, check if user is authenticated and has a team
            # Otherwise, list teams and ask user to select one
            if not team_id and not team_name:
                # Check if user is authenticated and has a team
                if shortcut_server.authenticated_user:
                    team_ids = shortcut_server.authenticated_user.get("group_ids", [])
                    if team_ids and len(team_ids) > 0:
                        team_id = team_ids[0]  # Use the first team if multiple
                    else:
                        # User has no teams, list available teams
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
                            text="Please provide either a team ID or team name from the list below and try again:\n\n" + 
                                "\n".join(formatted_teams)
                        )]
                else:
                    # User is not authenticated, list available teams
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
                        text="Please provide either a team ID or team name from the list below and try again:\n\n" + 
                            "\n".join(formatted_teams)
                    )]
            
            # If team_name is provided, find the corresponding team_id
            if team_name and not team_id:
                teams = await make_shortcut_request("GET", "groups")
                for team in teams:
                    if team.get("name", "").lower() == team_name.lower():
                        team_id = team.get("id")
                        break
                
                if not team_id:
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
                "workflow_state_id": workflow_state_id,
            }
            
            # Add group_id (team_id) if provided
            if team_id:
                # Shortcut API uses group_id for teams
                # Team IDs can be either integers or UUIDs, so we don't need to convert
                story_data["group_id"] = team_id
            
            # Add epic_id if provided
            if epic_id:
                # Epic IDs can be either integers or UUIDs, so we don't need to convert
                story_data["epic_id"] = epic_id
            
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
                
            return [types.TextContent(
                type="text",
                text="Projects have been deprecated by Shortcut. Please use teams instead. You can list teams using the list-teams tool."
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
                
            # Handle epic_id if provided
            if epic_id := arguments.get("epic_id"):
                # Epic IDs can be either integers or UUIDs, so we don't need to convert
                story_data["epic_id"] = epic_id
            
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
                # Shortcut API uses group_id for teams
                # Team IDs can be either integers or UUIDs, so we don't need to convert
                story_data["group_id"] = team_id
            
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

        elif name == "health-check":
            # This tool is used to check the health and connectivity of the Shortcut MCP server
            try:
                # Test Shortcut API connectivity
                start_time = time.time()
                await make_shortcut_request("GET", "member", max_retries=1, base_timeout=10.0)
                api_latency = time.time() - start_time
                
                # Get memory usage if psutil is available
                memory_info = ""
                try:
                    import psutil
                    process = psutil.Process(os.getpid())
                    memory_usage = process.memory_info().rss / 1024 / 1024  # MB
                    memory_info = f"Memory Usage: {memory_usage:.1f} MB\n"
                except ImportError:
                    pass
                
                # Get uptime information
                inactivity_time = shortcut_server.get_inactivity_time()
                
                # Get authenticated user info
                user_info = "Not authenticated"
                if shortcut_server.authenticated_user:
                    user_info = shortcut_server.authenticated_user.get("name", "Unknown")
                
                return [types.TextContent(
                    type="text",
                    text=(
                        f"✅ Shortcut MCP Server is healthy\n"
                        f"API Latency: {api_latency:.2f}s\n"
                        f"{memory_info}"
                        f"Inactive for: {inactivity_time:.1f}s\n"
                        f"Authenticated as: {user_info}\n"
                        f"HTTP Client: {'Active' if http_client else 'Not initialized'}"
                    )
                )]
            except Exception as e:
                return [types.TextContent(
                    type="text",
                    text=f"❌ Shortcut MCP Server is experiencing issues: {str(e)}"
                )]

        elif name == "get-story":
            # Get a specific story by ID
            story_id = arguments.get("story_id")
            if not story_id:
                return [types.TextContent(
                    type="text",
                    text="Please provide a story ID."
                )]
            
            try:
                # Clean the story ID (remove any non-numeric characters)
                original_id = story_id
                story_id = re.sub(r'[^0-9]', '', story_id)
                
                if not story_id:
                    return [types.TextContent(
                        type="text",
                        text=f"Invalid story ID: '{original_id}'. Please provide a numeric ID."
                    )]
                
                # Make a direct API call to get the story by ID (much faster than search)
                try:
                    story = await make_shortcut_request("GET", f"stories/{story_id}")
                    
                    # Format the story with more details since this is a direct lookup
                    formatted_story = await format_story_detailed(story)
                    
                    return [types.TextContent(
                        type="text",
                        text=f"Story details:\n\n{formatted_story}"
                    )]
                except ShortcutAPIError as e:
                    if "404" in str(e):
                        # If the story is not found, try to search for it
                        return [types.TextContent(
                            type="text",
                            text=f"❌ Story with ID {story_id} not found. You might want to try searching for it using the search-stories tool."
                        )]
                    else:
                        raise  # Re-raise the exception to be caught by the outer try-except
            except ShortcutAPIError as e:
                return [types.TextContent(
                    type="text",
                    text=f"❌ Error retrieving story: {e}"
                )]
            except Exception as e:
                print(f"Unexpected error in get-story: {type(e).__name__}: {e}", file=sys.stderr)
                return [types.TextContent(
                    type="text",
                    text=f"An unexpected error occurred while retrieving the story: {str(e)}"
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
    
    # Set up a watchdog timer to detect and handle potential deadlocks
    async def watchdog_timer():
        while True:
            await asyncio.sleep(60)  # Check every minute
            
            # Log that the server is still running
            inactivity_time = shortcut_server.get_inactivity_time()
            print(f"Watchdog timer: Server is still running (inactive for {inactivity_time:.1f} seconds)")
            
            # If the server has been inactive for too long (10 minutes), perform a health check
            if inactivity_time > 600:
                print("Server has been inactive for too long. Performing health check...")
                try:
                    # Try a simple API call to check if the connection is still working
                    await make_shortcut_request("GET", "member", max_retries=1, base_timeout=10.0)
                    print("Health check passed. Server is still responsive.")
                except Exception as e:
                    print(f"Health check failed: {str(e)}. Resetting connection...")
                    # Reset the HTTP client
                    await cleanup_http_client()
                
                # Reset the activity timer to avoid continuous health checks
                shortcut_server.update_activity()
    
    # Create a task for the watchdog
    watchdog_task = asyncio.create_task(watchdog_timer())
    
    try:
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            # Set up a timeout for the server run
            try:
                await asyncio.wait_for(
                    shortcut_server.server.run(
                        read_stream,
                        write_stream,
                        InitializationOptions(
                            server_name="shortcut",
                            server_version="0.2.2",
                            capabilities=shortcut_server.server.get_capabilities(
                                notification_options=NotificationOptions(),
                                experimental_capabilities={},
                            ),
                        ),
                    ),
                    timeout=None  # No timeout for the overall server, but individual operations will have timeouts
                )
            except asyncio.TimeoutError:
                print("Server operation timed out. Restarting...")
                # Instead of exiting, we could implement a restart mechanism here
            except Exception as e:
                print(f"Server error: {str(e)}")
                raise
    finally:
        # Clean up the watchdog task
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass
        
        # Clean up the HTTP client
        await cleanup_http_client()

if __name__ == "__main__":
    asyncio.run(main())
