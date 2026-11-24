# Known limits

What the first pre-release does not do. Each limit links to the page that has the detail.

- **State is in memory.** What a restart loses (the checkpointer, the A2A task store and the request-state keys) stays in the process unless you bring a durable one. [Durable state](https://github.com/timezlab/ext-r2c/blob/main/python/README.md#remote)
- **No authentication.** `Remote` adds none: each door names the owner of a request from what the deployment gives it, so put authentication in front before anything reaches a network. [Identity](https://github.com/timezlab/ext-r2c/blob/main/python/README.md#remote)
- **Loopback only.** The MCP door answers `421` to a `Host` that is not a loopback address until you name the public host. [The host guard](https://github.com/timezlab/ext-r2c/blob/main/python/README.md#remote)
- **One hop, no loop guard.** A question is not relayed through more than one hop, and nothing stops two agents that call each other's agents from looping. [What the example does not do](https://github.com/timezlab/ext-r2c/blob/main/examples/langgraph_agent/README.md#what-this-example-does-not-do)
- **MCP Tasks is not supported.** A tool call that runs longer than the client's request timeout fails on the client's side. [The MCP door](https://github.com/timezlab/ext-r2c/blob/main/python/README.md#the-mcp-door)
- **Not on PyPI.** Install the wheel by its full address from the release page; the bare name `ext-r2c` on PyPI is not this project. [Install](https://github.com/timezlab/ext-r2c/blob/main/python/README.md#install)
- **Version 1 of the standard is a draft.** Names and shapes may change until it has its first outside adopter, and the package's version is a separate number. [Versioning](https://github.com/timezlab/ext-r2c/blob/main/standard/v1/README.md#15-versioning)
