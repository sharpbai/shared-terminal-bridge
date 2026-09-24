# Proof-of-concept and baseline programs

Files in this directory preserve historical protocol experiments and executable end-to-end baselines. They are not the primary implementation entry points.

- Start production changes from `docs/code-structure.md` and the registries under `bridge/protocol/` or `mcp_server/tools/`.
- Read a PoC only when changing the baseline or investigating the specific behavior named by that file.
- Do not copy PoC-local protocol or lifecycle logic into production without reconciling it with current STB safety rules.
- The automated baseline tests execute selected PoCs and must continue to pass after structural changes.
