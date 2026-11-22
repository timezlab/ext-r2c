"""Bridges: one subpackage per agent framework (spec 006).

A bridge wraps an agent that already exists and gives it the shape of an ``AgentSource``
(``ext_r2c.core``), so the A2A door and the MCP door serve it with no change to the agent. Each
bridge sits behind its own extra and imports only ``ext_r2c.core`` and its framework's packages:
never a door, never another bridge. This package imports nothing.
"""
