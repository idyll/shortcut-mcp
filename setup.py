from setuptools import setup, find_packages

setup(
    name="shortcut-mcp",
    version="0.2.1",
    description="A Model Context Protocol (MCP) server for interacting with Shortcut",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.12",
    install_requires=[
        "mcp",
        "httpx",
        "python-dotenv",
    ],
    entry_points={
        "console_scripts": [
            "shortcut-mcp=shortcut_mcp.__main__:main",
        ],
    },
) 
