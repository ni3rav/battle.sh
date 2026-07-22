# battle.sh

Terminal two-player Battleship over an operator-owned WebSocket Relay.

## Local development (`ws://`, no Caddy)

Run the Relay on loopback, then connect two Players to that URL (or a fixed port):

```bash
uv sync
uv run python -m battle_sh.networking.relay_cli --bind-host 127.0.0.1 --port 8765
```

Use `ws://127.0.0.1:8765` from two terminal windows on the same machine. Caddy and TLS are not required for local play.

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
