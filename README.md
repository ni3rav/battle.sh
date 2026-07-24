# battle.sh

Terminal two-player Battleship over an operator-owned WebSocket Relay.

## Install

```bash
pip install battle-sh
```

This installs a single `battle-sh` command. You do not need to clone the repo,
run `uv`, or invoke Python modules to play.

## Play (`battle-sh`)

The whole experience is one executable with exactly three modes:

```bash
battle-sh relay     # run the Match Relay server
battle-sh host      # start a new game and print an Invite
battle-sh join      # join a game with an Invite (as the Guest)
```

Point clients at a relay with `--relay` (or the `BATTLE_SH_RELAY` environment
variable); it defaults to `ws://127.0.0.1:8765`.

```bash
# Terminal A — Relay
battle-sh relay --bind-host 127.0.0.1 --port 8765
```

```bash
# Terminal B — Host (prints an Invite phrase to share)
battle-sh host --relay ws://127.0.0.1:8765
```

```bash
# Terminal C — Guest (paste the Invite the Host printed)
battle-sh join --relay ws://127.0.0.1:8765 --invite alpha-tango-jesse-ironman
```

Against a hosted relay, use the `wss://` URL, e.g.
`battle-sh host --relay wss://relay.example.com`.

The Match UI shows a live scoreboard: active/remaining ships per side, hits,
current turn, match state, and a connection indicator for both players.

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
# Terminal B — Guest (paste the Invite phrase the Host prints)
uv run python -m battle_sh.ui guest --relay ws://127.0.0.1:8765 --invite alpha-tango-jesse-ironman
```

### Live Match UI

Fixed **three-band** layout: top = Match/role/turn + Match time; middle = wide board | phase-aware controls; bottom = status/errors. Match time starts when the Guest joins (not during Host lobby wait) and freezes on the Winner/Abandoned end screen.

### Key map

| Phase | Keys |
| --- | --- |
| Placement | `1`–`5` or Tab / Shift+Tab select ship; `w/a/s/d` or arrows move; `e` / `r` flip H↔V; `t` re-roll; `y` lock |
| Combat | `w/a/s/d` or arrows Aim (skips fired cells); `f` / Enter / Space fire |
| Any Live phase | first Ctrl+C warns (status), second confirms Abandon and sends `leave_match` (both sides end immediately; no reconnect grace; arm auto-clears) |

Waiting turns show a spinner; only Ctrl+C is honored for quit. Invite for Guest stays CLI `--invite` (or a one-shot paste before Live UI). Caddy and TLS are not required for local play.

### Manual Host/Guest smoke checklist

On a local Relay (commands above), in two terminals:

1. Host creates a Match; confirm lobby shows waiting-for-Guest (no Match time yet).
2. Guest joins with `--invite`; both see Match time start; three-band chrome stays stable.
3. Placement: move/rotate/re-roll with keys, then `y` to lock; opponent wait shows spinner.
4. Combat: Aim with arrows/WASD, fire with `f`; confirm skip over already-fired cells.
5. Quit path: two-step Ctrl+C Abandons immediately for both players (`leave_match`); both see `Match Abandoned. Exiting.`; end screen shows frozen Match time.
6. Optional: play through to Winner and confirm frozen Match time on the end screen.

## Run a Relay on any cloud VM (`wss://`)

You rent (or already have) a normal Linux virtual machine somewhere — DigitalOcean, Hetzner, AWS, a home box, whatever. This project does **not** create the VM for you and is not tied to one cloud. You point DNS at the machine, SSH in with our scripts, and they install the Relay.

Works best on **Debian/Ubuntu** (the script can install Caddy with `apt`). On other distros, install Caddy yourself first, then run provision again.

### 1. Create a VM

In your cloud console: start a small Ubuntu VM, note its public IP, and make sure you can SSH as root (or a user that can sudo — today the scripts assume you SSH as the user who can write `/opt` and manage systemd; root is simplest).

Open ports **22** (SSH), **80**, and **443** on the firewall / security group.

### 2. Point a domain at the VM

Pick a hostname players will use, e.g. `relay.example.com`.

In your DNS provider, create an **A** record (and **AAAA** if you use IPv6) from that name to the VM’s public IP. Wait until `dig +short relay.example.com` shows the right address.

Do this **before** provisioning. Caddy asks Let’s Encrypt for a real certificate for that name; if DNS is wrong, certs fail and `wss://` will not work.

### 3. Install the Relay from your laptop

On your laptop (this repo), with SSH access to the VM:

```bash
./scripts/provision-relay \
  --host root@YOUR_VM_IP \
  --domain relay.example.com \
  --email you@example.com
```

That copies the app to `/opt/battle-sh`, installs **uv** and **Caddy** if needed, writes a systemd unit (`battle-sh-relay.service`), and starts Relay + Caddy. Caddy terminates HTTPS and forwards WebSockets to the Relay on `127.0.0.1:8765`.

Players then connect with:

```bash
uv run python -m battle_sh.ui host --relay wss://relay.example.com
uv run python -m battle_sh.ui guest --relay wss://relay.example.com --invite PASTE_INVITE
```

Preview files without touching a machine:

```bash
./scripts/provision-relay \
  --host root@YOUR_VM_IP \
  --domain relay.example.com \
  --email you@example.com \
  --dry-run \
  --output-dir /tmp/battle-sh-deploy
```

### 4. Tear it down

```bash
./scripts/deprovision-relay --host root@YOUR_VM_IP
```

Stops Relay and Caddy, removes the unit, Caddyfile, and `/opt/battle-sh`. The Caddy package may stay installed on the OS.

### Practice the same flow in Docker (no real cloud)

Want to rehearse provision without renting a VM? `scripts/practice-vm` boots a systemd Ubuntu container with SSH — a stand-in “cloud box” on your machine — then runs the real provision script against it.

Docker is **not** how we deploy in production (uv + Caddy + systemd on a real host is). This is only a local practice VM. Because there is no public DNS, provision uses `--tls-internal` (Caddy’s local certificate). Real internet VMs should **not** pass that flag.

```bash
./scripts/practice-vm doctor    # up → provision → status → WebSocket smoke
# or step by step:
./scripts/practice-vm up
./scripts/practice-vm provision
./scripts/practice-vm status
./scripts/practice-vm smoke
./scripts/practice-vm down
```

SSH into the practice box: `ssh -i .scratch/practice-vm/id_ed25519 -p 2222 root@127.0.0.1`
