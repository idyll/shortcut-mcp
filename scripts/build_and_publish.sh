#!/bin/bash
# Script to build and publish the shortcut-mcp package

set -e  # Exit on error

# Check if build and twine are installed
if ! pip show build > /dev/null 2>&1; then
    echo "Installing build package..."
    pip install build
fi

if ! pip show twine > /dev/null 2>&1; then
    echo "Installing twine package..."
    pip install twine
fi

# Clean up previous builds
echo "Cleaning up previous builds..."
rm -rf dist/ build/ *.egg-info

# Build the package
echo "Building the package..."
python -m build

# List the built packages
echo "Built packages:"
ls -l dist/

# Ask if the user wants to publish
read -p "Do you want to publish these packages to PyPI? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Publishing to PyPI..."
    python -m twine upload dist/*
else
    echo "Skipping PyPI upload."
    echo "To publish later, run: python -m twine upload dist/*"
fi

echo "Done!" 
