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

Placement uses immediate keys (no Enter): a random layout is ready by default. Press `1`–`5` or Tab/Shift+Tab to select a ship, `w/a/s/d` or arrows to move, `e` or `r` to flip orientation, `t` to re-roll, `y` to lock, `q` to quit. During play, enter shots as coordinates like `B7`, or `q` to quit. Caddy and TLS are not required for local play.

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
