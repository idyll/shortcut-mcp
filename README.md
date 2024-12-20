# Shortcut MCP Server

A Model Context Protocol (MCP) server for interacting with Shortcut (formerly Clubhouse).

## Features

- View projects, stories, epics, and objectives
- Search through stories
- Create new stories, epics, and objectives
- Safe operations only (no updates or deletions)

## Setup

1. Install dependencies:
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv add -r requirements.txt
```

2. Set up your environment:
```bash
cp .env.example .env
# Edit .env and add your Shortcut API token
```

3. Run the server:
```bash
python shortcut_server.py
```

## Using with Claude Desktop

Add this to your Claude Desktop config:

On MacOS (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{
    "mcpServers": {
        "shortcut": {
            "command": "uv",
            "args": ["run", "/absolute/path/to/shortcut_server.py"],
            "env": {
                "SHORTCUT_API_TOKEN": "your_token_here"
            }
        }
    }
}
```

On Windows (`%AppData%\Claude\claude_desktop_config.json`):
```json
{
    "mcpServers": {
        "shortcut": {
            "command": "uv",
            "args": ["run", "C:\\absolute\\path\\to\\shortcut_server.py"],
            "env": {
                "SHORTCUT_API_TOKEN": "your_token_here"
            }
        }
    }
}
```

## Testing

You can test the server using the MCP Inspector:
```bash
npx @modelcontextprotocol/inspector uv run shortcut_server.py
```

## Safety Features

This server implements read-only operations with safe creation capabilities:
- Only allows GET (read) and POST (create) operations
- No modification or deletion of existing data
- All operations are attributed to the API token owner