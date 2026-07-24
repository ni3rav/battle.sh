## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Cursor Cloud specific instructions

`battle-sh` is a terminal two-player Battleship game (`src/battle_sh`) played over an
operator-owned WebSocket Relay. Toolchain is `uv` (installed to `~/.local/bin`; the update
script refreshes deps). Standard commands live in `README.md`; the gates match CI
(`.github/workflows/ci.yml`): `uv run pyright` (strict typecheck — this is the lint gate,
there is no separate linter) and `uv run pytest`.

To run/play locally, start the Relay then a Host and a Guest (see README "Local development"):
Relay `uv run python -m battle_sh.networking.relay_cli --bind-host 127.0.0.1 --port 8765`,
then `uv run python -m battle_sh.ui host|guest --relay ws://127.0.0.1:8765`. The Host prints
a random Invite phrase the Guest passes via `--invite`.

Non-obvious gotchas:
- Placement and Aim read keys off the event loop (worker thread / polling) so the
  WebSocket keepalive stays responsive while waiting for input. Lobby and
  "waiting for opponent" screens are async and stay alive indefinitely.
- Quit is two-step Ctrl+C only (not `q`). SIGINT is routed into the same QuitArm
  path so a confirmed quit sends `leave_match` and the opponent Abandons
  immediately instead of waiting on reconnect grace.
- `--grace-seconds` controls the reconnect grace window, not the keepalive.
- Manual/automated UI testing needs a PTY. Drive it with `tmux send-keys` (e.g. `y` locks a
  random placement, `f` fires at the current aim). The layout reflows to the terminal width.
- The `scripts/provision-relay` / `deprovision-relay` / `practice-vm` flows are for deploying
  a `wss://` Relay to a real VM (uv + Caddy + systemd) and are not needed for local play.
