# Shortcut MCP Server

A Model Context Protocol (MCP) server for interacting with Shortcut (formerly Clubhouse) directly from Claude.

## Acknowledgments

This project is based on the original work by [Antonio Lorusso](https://github.com/antoniolorusso). Mark Madsen's fork extends the original implementation with additional features including advanced search capabilities, improved CLI tools, and enhanced user experience.

## Features

- View projects, stories, epics, and objectives
- Search through stories with advanced filtering options
- Create new stories, epics, and objectives
- Safe operations only (no updates or deletions)
- Archived stories management (excluded by default, with option to include)

## What's New in 0.2.2

- **Enhanced Search Functionality**: Improved search capabilities with support for Shortcut's native query syntax
- **Advanced Query Operators**: Support for operators like `type:`, `state:`, `owner:`, `label:`, and more
- **Better Error Handling**: More detailed error messages and improved fallback mechanisms
- **Robust Story ID Handling**: Better handling of non-numeric characters in story IDs

## What's New in 0.2.1

- **Team Management**: Added support for assigning teams to stories using `team_id` and `team_name` parameters
- **New Tool**: Use the `list-teams` tool to see all available teams in your Shortcut workspace
- **Improved Reliability**: Better handling of parameters and error conditions
- **Enhanced Epic Support**: Improved support for linking stories to epics

## Installation

### Standard Installation

```bash
pip install shortcut-mcp
```

### MacOS Installation with Homebrew and pipx

For MacOS users, we recommend using [Homebrew](https://brew.sh/) and [pipx](https://pypa.github.io/pipx/) for a cleaner installation:

```bash
# Install pipx if you don't have it already
brew install pipx
pipx ensurepath

# Install shortcut-mcp
pipx install shortcut-mcp
```

This method installs shortcut-mcp in an isolated environment, preventing dependency conflicts with other Python packages.

### Upgrading

To upgrade to the latest version:

```bash
# Standard upgrade
pip install --upgrade shortcut-mcp

# If installed with pipx
pipx upgrade shortcut-mcp
```

## Quick Start

### 1. Set up with Claude Desktop

```bash
# Install and set up in one step
shortcut-mcp setup
```

You'll be prompted for your Shortcut API token, which you can find in your Shortcut settings.

> **Security Note**: Your API token grants access to your Shortcut account. Never share it publicly or commit it to version control. The `.env` file is included in `.gitignore` to help prevent accidental exposure.

### 2. Using in Claude

After setup, you can now use the Shortcut tools directly in Claude Desktop. Try these commands:

- `list-workflows` - See all workflow states
- `list-my-stories` - View stories assigned to you
- `list-stories-by-state-name` - View stories in a specific state
- `advanced-search-stories` - Find stories with multiple filters
- `list-projects` - See all available projects
- `list-teams` - View all teams in your Shortcut workspace
- `search-stories` - Find stories by keywords
- `list-archived-stories` - View archived stories
- `list-my-archived-stories` - View your archived stories

## Manual Usage

If you want to run the server manually:

```bash
# Set your API token
export SHORTCUT_API_TOKEN=your_token_here

# Start the server
shortcut-mcp start
```

## Development Setup

1. Clone the repository:

```bash
git clone https://github.com/idyll/shortcut-mcp.git
cd shortcut-mcp
```

2. Install Python with asdf:

```bash
asdf install
```

3. Create virtual environment and install dependencies:

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .  # Install package in editable mode
```

4. Set up your environment:

```bash
cp .env.example .env
# Edit .env and add your Shortcut API token
```

5. Run the server:

```bash
python -m shortcut_mcp
```

## Project Structure

```
shortcut-mcp/
├── src/
│   └── shortcut_mcp/      # Main package directory
│       ├── __init__.py    # Package initialization
│       ├── __main__.py    # Entry point
│       ├── cli.py         # CLI implementation
│       └── server.py      # Server implementation
├── pyproject.toml         # Project configuration
├── .tool-versions         # ASDF version configuration
└── README.md
```

## Using with Claude Desktop

The `shortcut-mcp setup` command will automatically configure Claude Desktop for you. If you want to do it manually, add this to your Claude Desktop config:

On MacOS (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "shortcut": {
      "command": "shortcut-mcp",
      "args": ["start"],
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
      "command": "shortcut-mcp",
      "args": ["start"],
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
npx @modelcontextprotocol/inspector shortcut-mcp start
```

## Safety Features

This server implements read-only operations with safe creation capabilities:

- Only allows GET (read) and POST (create) operations
- No modification or deletion of existing data
- All operations are attributed to the API token owner

## Development

### Python Version Management

This project uses [asdf](https://asdf-vm.com/) for Python version management. The required Python version is specified in `.tool-versions`.

```bash
# Install Python with asdf
asdf install python

# The correct version will be automatically selected based on .tool-versions
```

### Code Quality

We use pylint for code quality checks. Run it with:

```bash
pylint src/shortcut_mcp
```

### Building and Publishing

Once your code is ready:

```bash
# Install build tools
pip install build twine

# Build the package
python -m build

# Upload to PyPI
python -m twine upload dist/*
```

## Advanced Search Features

The Shortcut MCP server provides powerful search capabilities through the `advanced-search-stories` tool:

### Search Parameters

- **Owner vs. Requestor**: Distinguish between the person assigned to a story (owner) and the person who requested it
- **Workflow State**: Filter by specific workflow states like "In Development" or "Ready for Review"
- **Time-based Filtering**: Find stories based on when they were created or updated
  - `created_after` / `created_before`: Filter by creation date
  - `updated_after` / `updated_before`: Filter by last update date
- **Archived Stories**: All search tools exclude archived stories by default
  - Use `include_archived: true` parameter to include archived stories
  - Dedicated tools for working with archived stories: `list-archived-stories` and `list-my-archived-stories`

### Example Queries

In Claude, you can use commands like:

- "Find stories requested by John but owned by Sarah"
- "Show me stories in the Ready for Review state created in the last month"
- "Search for stories updated after 2023-01-01 in the In Development state"
- "List archived stories in the Done state"
- "Show my archived stories from the last quarter"

This makes it easy to find exactly the stories you're looking for, even in large projects with many tickets.

