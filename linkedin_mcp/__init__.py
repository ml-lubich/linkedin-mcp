"""linkedin-mcp: LinkedIn CLI + MCP server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("linkedin-mcp")
except PackageNotFoundError:
    __version__ = "0.2.0"
