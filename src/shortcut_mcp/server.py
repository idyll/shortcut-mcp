import asyncio
import os
from typing import Any, Optional
import httpx
from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.types as types
import mcp.server.stdio

# Initialize server
server = Server("shortcut")

# Constants
API_BASE_URL = "https://api.app.shortcut.com/api/v3"
SHORTCUT_API_TOKEN = os.getenv("SHORTCUT_API_TOKEN")

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
    
    # Safety check: POST requests are only allowed for creation endpoints
    if method == "POST" and not any(endpoint.endswith(x) for x in ["stories", "epics", "objectives"]):
        raise ValueError(f"POST requests are only allowed for creation endpoints, not for {endpoint}")
    if not SHORTCUT_API_TOKEN:
        raise ValueError("SHORTCUT_API_TOKEN environment variable not set")

    headers = {
        "Content-Type": "application/json",
        "Shortcut-Token": SHORTCUT_API_TOKEN
    }

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

def format_objective(objective: dict) -> str:
    """Format an objective into a readable string"""
    return (
        f"Objective: {objective['name']}\n"
        f"Status: {objective.get('status', 'Unknown')}\n"
        f"Description: {objective.get('description', 'No description')}\n"
        f"URL: {objective.get('app_url', '')}\n"
        "---"
    )

def format_epic(epic: dict) -> str:
    """Format an epic into a readable string"""
    return (
        f"Epic: {epic['name']}\n"
        f"Status: {epic.get('state', 'Unknown')}\n"
        f"Description: {epic.get('description', 'No description')}\n"
        f"Milestone: {epic.get('milestone', {}).get('name', 'None')}\n"
        f"URL: {epic.get('app_url', '')}\n"
        "---"
    )

def format_story(story: dict) -> str:
    """Format a story into a readable string"""
    return (
        f"Story {story['id']}: {story['name']}\n"
        f"Status: {story.get('workflow_state', {}).get('name', 'Unknown')}\n"
        f"Type: {story.get('story_type', 'Unknown')}\n"
        f"Description: {story.get('description', 'No description')}\n"
        f"URL: {story.get('app_url', '')}\n"
        "---"
    )

@shortcut_server.server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available Shortcut tools - Read-only operations with safe creation"""
    user_info = f" (Will be created as {shortcut_server.authenticated_user.get('name')})"
    return [
        types.Tool(
            name="search-stories",
            description="Search for stories in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (e.g. story title, description, or ID)",
                    },
                },
                "required": ["query"],
            },
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

        types.Tool(
            name="list-projects",
            description="List all projects in Shortcut",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name=            "list-workflows",
            description="List all workflows and their states",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="list-objectives",
            description="List all objectives in Shortcut",
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
            query = arguments.get("query")
            search_results = await make_shortcut_request(
                "GET",
                "search/stories",
                params={"query": query}
            )
            
            stories = search_results.get("data", [])
            if not stories:
                return [types.TextContent(
                    type="text",
                    text=f"No stories found matching query: {query}"
                )]

            formatted_stories = [format_story(story) for story in stories[:10]]
            return [types.TextContent(
                type="text",
                text="Found stories:\n\n" + "\n".join(formatted_stories)
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
                text=f"Created new story:\n\n{format_story(new_story)}"
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

        else:
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
                server_version="0.1.0",
                capabilities=shortcut_server.server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())
