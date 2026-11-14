{
  pkgs,
  lib,
  config,
  inputs,
  ...
}: {
  # https://devenv.sh/basics/
  env.GREET = "pivotal winter 2027 workstest";

  # https://devenv.sh/packages/
  packages = with pkgs; [pi-coding-agent];

  # https://devenv.sh/languages/
  # languages.rust.enable = true;

  # https://devenv.sh/processes/
  # processes.dev.exec = "${lib.getExe pkgs.watchexec} -n -- ls -la";

  # https://devenv.sh/services/
  # services.postgres.enable = true;

  # https://devenv.sh/scripts/
  scripts.hello.exec = ''
    echo hello from $GREET
  '';

  # `run` starts the trajectory review UI on the good-runs subset.
  # Extra arguments go to the server, e.g. `run --port 9000` or `run --raw`.
  scripts.run.exec = ''
    cd "$DEVENV_ROOT" && exec uv run scripts/serve_viewer.py "$@"
  '';

  # `replay` replays a recorded run in pi with the commit-first review gate.
  # No argument: a random good run. Or `replay <traj_id>`, `replay --list`.
  scripts.replay.exec = ''
    exec "$DEVENV_ROOT/scripts/replay.sh" "$@"
  '';

  # https://devenv.sh/basics/
  enterShell = ''
    hello         # Run scripts directly
    echo "Type 'run' to start the trajectory review UI (http://127.0.0.1:8765/)"
    echo "Type 'replay' to review a recorded run in pi with the commit-first gate"
    git --version # Use packages
  '';

  # https://devenv.sh/tasks/
  # tasks = {
  #   "myproj:setup".exec = "mytool build";
  #   "devenv:enterShell".after = [ "myproj:setup" ];
  # };

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';

  # https://devenv.sh/git-hooks/
  # git-hooks.hooks.shellcheck.enable = true;

  # See full reference at https://devenv.sh/reference/options/
}
