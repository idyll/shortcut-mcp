#!/usr/bin/env python
"""Tests for the shortcut-mcp CLI."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Add the src directory to the path so we can import the package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from shortcut_mcp.cli import get_config_path, setup_claude_desktop, main


class TestCLI(unittest.TestCase):
    """Tests for the CLI module."""

    @patch('platform.system')
    def test_get_config_path_macos(self, mock_system):
        """Test get_config_path on macOS."""
        mock_system.return_value = "Darwin"
        path = get_config_path()
        self.assertIn("Library/Application Support/Claude/claude_desktop_config.json", path)

    @patch('platform.system')
    def test_get_config_path_windows(self, mock_system):
        """Test get_config_path on Windows."""
        mock_system.return_value = "Windows"
        with patch.dict('os.environ', {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
            path = get_config_path()
            self.assertIn("Claude", path)
            self.assertIn("claude_desktop_config.json", path)

    @patch('platform.system')
    def test_get_config_path_unsupported(self, mock_system):
        """Test get_config_path on unsupported platform."""
        mock_system.return_value = "Linux"
        with self.assertRaises(SystemExit):
            get_config_path()

    @patch('shortcut_mcp.cli.get_config_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='{}')
    @patch('json.dump')
    @patch('os.makedirs')
    def test_setup_claude_desktop(self, mock_makedirs, mock_json_dump, mock_open, mock_get_config_path):
        """Test setup_claude_desktop."""
        mock_get_config_path.return_value = "/path/to/config.json"
        setup_claude_desktop("test_token")
        mock_makedirs.assert_called_once()
        mock_open.assert_called_with("/path/to/config.json", 'w')
        mock_json_dump.assert_called_once()
        # Check that the token is in the config
        args, kwargs = mock_json_dump.call_args
        self.assertEqual(args[0]["mcpServers"]["shortcut"]["env"]["SHORTCUT_API_TOKEN"], "test_token")

    @patch('argparse.ArgumentParser.parse_args')
    @patch('shortcut_mcp.cli.setup_claude_desktop')
    @patch('asyncio.run')
    def test_main_setup(self, mock_asyncio_run, mock_setup, mock_parse_args):
        """Test main with setup command."""
        mock_args = MagicMock()
        mock_args.command = "setup"
        mock_args.token = "test_token"
        mock_parse_args.return_value = mock_args
        main()
        mock_setup.assert_called_with("test_token")
        mock_asyncio_run.assert_not_called()

    @patch('argparse.ArgumentParser.parse_args')
    @patch('shortcut_mcp.cli.setup_claude_desktop')
    @patch('asyncio.run')
    @patch('shortcut_mcp.server.main')
    def test_main_start(self, mock_server_main, mock_asyncio_run, mock_setup, mock_parse_args):
        """Test main with start command."""
        mock_args = MagicMock()
        mock_args.command = "start"
        mock_args.token = None
        mock_parse_args.return_value = mock_args
        
        # Create a mock coroutine
        async def mock_coro():
            return None
        mock_server_main.return_value = mock_coro()
        
        main()
        mock_setup.assert_not_called()
        mock_asyncio_run.assert_called_once()


if __name__ == '__main__':
    unittest.main() 
