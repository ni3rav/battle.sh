# battle.sh

Terminal two-player Battleship over an operator-owned WebSocket Relay.

## Local development (`ws://`, no Caddy)

### Checks

Same gates as CI:

```bash
uv sync --group dev
uv run pyright
uv run pytest
```

### Play

Run the Relay on loopback, then open two terminals as Host and Guest:

```bash
uv sync
uv run python -m battle_sh.networking.relay_cli --bind-host 127.0.0.1 --port 8765
```

```bash
# Terminal A — Host
uv run python -m battle_sh.ui host --relay ws://127.0.0.1:8765
```

```bash
# Terminal B — Guest (paste the Invite the Host prints)
uv run python -m battle_sh.ui guest --relay ws://127.0.0.1:8765 --invite PASTE_INVITE
```

### Live Match UI

Fixed **three-band** layout: top = Match/role/turn + Match time; middle = wide board | phase-aware controls; bottom = status/errors. Match time starts when the Guest joins (not during Host lobby wait) and freezes on the Winner/Abandoned end screen.

### Key map

| Phase | Keys |
| --- | --- |
| Placement | `1`–`5` or Tab / Shift+Tab select ship; `w/a/s/d` or arrows move; `e` / `r` flip H↔V; `t` re-roll; `y` lock |
| Combat | `w/a/s/d` or arrows Aim (skips fired cells); `f` / Enter / Space fire |
| Any Live phase | `q` quit (Abandon); first Ctrl+C warns, second within ~3s Abandons (arm auto-clears) |

Waiting turns show a spinner; only `q` and Ctrl+C are honored. Invite for Guest stays CLI `--invite` (or a one-shot paste before Live UI). Caddy and TLS are not required for local play.

### Manual Host/Guest smoke checklist

On a local Relay (commands above), in two terminals:

1. Host creates a Match; confirm lobby shows waiting-for-Guest (no Match time yet).
2. Guest joins with `--invite`; both see Match time start; three-band chrome stays stable.
3. Placement: move/rotate/re-roll with keys, then `y` to lock; opponent wait shows spinner.
4. Combat: Aim with arrows/WASD, fire with `f`; confirm skip over already-fired cells.
5. Quit path: `q` or two-step Ctrl+C Abandons; opponent sees Abandoned; end screen shows frozen Match time.
6. Optional: play through to Winner and confirm frozen Match time on the end screen.

## Hosted Relay (`wss://` via Caddy + systemd)

Any SSH-able Linux VM works — there are no AWS-specific (or other cloud-vendor) create/destroy helpers. You bring the host; these scripts only install the Relay stack. Automated Caddy install uses **apt** (Debian/Ubuntu). On other distros, install Caddy yourself first, then re-run provision.

### DNS before certificates

Create an **A** and/or **AAAA** record for your Relay domain that points at the VM **before** provisioning. Caddy obtains TLS certificates for that name; if DNS is missing or still propagating, certificate issuance will fail.

### Provision

```bash
./scripts/provision-relay \
  --host root@YOUR_VM_IP \
  --domain relay.example.com \
  --email you@example.com
```

This installs **uv**, the Relay app under `/opt/battle-sh`, **Caddy** (HTTPS/WSS termination to `127.0.0.1:8765`), and a **systemd** unit (`battle-sh-relay.service`). Players then connect with `wss://relay.example.com`.

Dry-run (writes `Caddyfile` and the systemd unit locally, no SSH):

```bash
./scripts/provision-relay \
  --host root@YOUR_VM_IP \
  --domain relay.example.com \
  --email you@example.com \
  --dry-run \
  --output-dir /tmp/battle-sh-deploy
```

### Deprovision

```bash
./scripts/deprovision-relay --host root@YOUR_VM_IP
```

Stops and disables the Relay and Caddy units, removes the Relay unit file, Caddyfile, and `/opt/battle-sh`. The Caddy OS package may remain installed; remove it with your package manager if you want it gone.
