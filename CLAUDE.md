# pivotal-winter-2027

## Python tooling

Use `uv` for everything Python in this repo. Do not call `pip`, `python -m venv`, or a bare `python`.

- Add a dependency: `uv add <package>` (dev-only: `uv add --dev <package>`)
- Run a script or command: `uv run <script.py | command>`
- Sync the environment: `uv sync`

## Pi coding agent documentation

Full Pi documentation and example extensions are vendored in this repo:

| Topic | File |
|---|---|
| **Extensions** | `docs/extensions.md` |
| **Custom Providers** | `docs/custom-provider.md` |
| **Virtual Models** | `docs/virtual-models.md` |
| **Terminal UI** | `docs/tui.md` |
| **Packages** | `docs/packages.md` |
| **MCP Servers** | `docs/mcp.md` |
| **Skills** | `docs/skills.md` |
| **Prompt Templates** | `docs/prompt-templates.md` |
| **Keybindings** | `docs/keybindings.md` |
| **SDK** | `docs/sdk.md` |
| **Codemode** | `docs/codemode.md` |
| **Environment Variables** | `docs/environment-variables.md` |
| **Models / Providers** | `docs/models.md`, `docs/providers.md` |
| **Compaction** | `docs/compaction.md` |
| **Sessions** | `docs/sessions.md` |
| **Security** | `docs/security.md` |

Checked example extensions live in `examples/extensions/` (~80 examples). Key references:

| Goal | Example |
|---|---|
| Minimal custom tool | `examples/extensions/hello.ts` |
| Confirm/block tool calls | `examples/extensions/permission-gate.ts` |
| Modify prompt sections | `examples/extensions/prompt-customizer.ts` |
| Branch-aware state | `examples/extensions/todo.ts` |
| Register tools after startup | `examples/extensions/dynamic-tools.ts` |
| Nested model calls | `examples/extensions/qna.ts` |
| Custom editor | `examples/extensions/modal-editor.ts` |
| Shutdown cleanup | `examples/extensions/auto-commit-on-exit.ts` |
| Provider with OAuth | `examples/extensions/custom-provider-gitlab-duo/` |
| Virtual model router | `examples/extensions/jev-router.ts` |
| Handoff to new session | `examples/extensions/handoff.ts` |

## Data

Datasets live in the Hugging Face cache (`~/.cache/huggingface/hub`, or `$HF_HOME`), not in the repo. Fetch them with:

```
uv run scripts/download_trajectories.py
```

This caches two dataset repos as parquet shards:

- `SWE-bench/SWE-smith-trajectories`: agent runs
- `SWE-bench/SWE-smith`: the task instances behind each run

Resolve the local path with `snapshot_download(repo_id, repo_type="dataset")`; it returns immediately once cached.
