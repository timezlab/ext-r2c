# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Repository skeleton: Python package `ext-r2c` exposing `URI`, `MCP_KEY` and
  `STANDARD_VERSION`, CI that tests the built wheel.
- The R2C standard v1 (draft): the normative text in `standard/v1/README.md`,
  with tagged rules for activation, placement, the six kinds, the A2A and MCP
  bindings, identifiers, safety and versioning.
- JSON Schemas for `question`, `approval`, `answer`, `artifact` metadata,
  `activity` and `usage` in `standard/v1/schema/`.
- Wire examples for A2A and MCP in `standard/v1/examples/`, including a full
  streamed run, and objects each schema must reject.
- Checks that validate every example's objects and envelopes (against the
  a2a-sdk and MCP SDK types) and that every wire rule has an example.
- The wheel ships the schemas as `ext_r2c/schema/v1/`.
