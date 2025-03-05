# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2025-03-06

### Added

- Enhanced search functionality with support for Shortcut's native query syntax
- Support for advanced query operators like `type:`, `state:`, `owner:`, `label:`, and more
- Improved tool descriptions with detailed parameter explanations

### Fixed

- Fixed issues with the `search-stories` implementation to properly handle search parameters
- Improved error handling with more detailed error messages
- Enhanced handling of non-numeric characters in story IDs
- Added fallback mechanisms for search operations

## [0.2.1] - 2025-03-05

### Added

- Added support for `team_id` and `team_name` parameters in the `update-story` handler
- Added a new `list-teams` tool to show available teams in Shortcut

### Fixed

- Fixed the `update-story` handler to properly handle `epic_id` and `epic_name` parameters
- Fixed the `list-workflows` and `list-projects` tools to properly handle empty properties in their input schemas
- Fixed handling of None arguments in all tool handlers
- Improved type conversion for numeric parameters like `epic_id`, `project_id`, and `team_id`

## [0.2.0] - 2025-03-01

### Added

- Initial public release
- Support for searching, listing, and updating Shortcut stories
- Support for creating new stories and epics
- Integration with Claude Desktop
