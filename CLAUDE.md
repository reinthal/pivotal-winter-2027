# pivotal-winter-2027

## Python tooling

Use `uv` for everything Python in this repo. Do not call `pip`, `python -m venv`, or a bare `python`.

- Add a dependency: `uv add <package>` (dev-only: `uv add --dev <package>`)
- Run a script or command: `uv run <script.py | command>`
- Sync the environment: `uv sync`

## Data

`data/` is gitignored. Fetch the SWE-smith trajectories with:

```
uv run scripts/download_trajectories.py
```

They land in `data/swe-smith-trajectories/` as parquet shards.
