# Spark — Remote SSH via Cloudflare Tunnel

How this box is reachable over SSH at `spark.huikang.dev` from anywhere on
the public internet, despite living behind a residential NAT. Setup performed
on 2026-04-25.

## Why a tunnel

The box sits on a home LAN (`192.168.1.150`) behind a typical consumer router.
Options considered:

- **Router port-forwarding + DDNS** — works only if the ISP doesn't CGNAT, and
  exposes :22 directly to the public internet.
- **Direct IPv6 + AAAA record** — the box has a routable IPv6, but IPv4-only
  client networks (corporate Wi-Fi, some carriers) can't reach it.
- **Tailscale SSH** — easiest for personal devices, but doesn't give you a
  literal `huikang.dev` hostname; client must run Tailscale.
- **Cloudflare Tunnel (chosen)** — `huikang.dev` is already on Cloudflare DNS,
  so this reuses the existing zone. No router config, traverses NAT/CGNAT,
  free, and the public hostname `spark.huikang.dev` resolves identically from
  any network. Trade-off: SSH client needs `cloudflared` because Cloudflare's
  free proxy doesn't pass raw TCP on :22 — the SSH bytes get wrapped in
  WebSocket-over-HTTPS:443.

## Architecture

```
laptop ssh → cloudflared (client, ProxyCommand) → wss/443 →
  Cloudflare edge (sjc01/05/06/08) → Cloudflare Tunnel →
  cloudflared.service on the Spark → localhost:22 → sshd
```

Public DNS for `spark.huikang.dev` is a CNAME to a tunnel-specific
`<tunnel-id>.cfargotunnel.com`, managed automatically by `cloudflared`.

## Server-side state (this box)

- `cloudflared` package: installed from `pkg.cloudflare.com` apt repo
  (`/usr/bin/cloudflared`).
- Tunnel name: `spark`, ID: `a7491515-06b1-458e-9fc8-2de3a4514206`.
- Systemd unit: `cloudflared.service` (enabled at boot, auto-restart).
- Config: `/etc/cloudflared/config.yml`
  ```yaml
  tunnel: a7491515-06b1-458e-9fc8-2de3a4514206
  credentials-file: /etc/cloudflared/a7491515-06b1-458e-9fc8-2de3a4514206.json
  ingress:
    - hostname: spark.huikang.dev
      service: ssh://localhost:22
    - service: http_status:404
  ```
- Tunnel credentials JSON: `/etc/cloudflared/<tunnel-id>.json`, root:root, 0600.
  This file is the secret — anyone with it can run the tunnel.
- Cloudflare account auth cert: `~/.cloudflared/cert.pem` (used only for
  `cloudflared tunnel ...` admin commands).

## sshd hardening

Key-only auth, password and keyboard-interactive disabled:

`/etc/ssh/sshd_config.d/50-key-only.conf`:
```
PasswordAuthentication no
KbdInteractiveAuthentication no
```

Effective settings (`sudo sshd -T | grep -i auth`):
```
pubkeyauthentication yes
passwordauthentication no
kbdinteractiveauthentication no
```

`PermitRootLogin without-password` is Ubuntu's default; harmless because
`root` has no `authorized_keys` on this box.

## Authorized clients

`~htong/.ssh/authorized_keys` — one entry per client device that is allowed
to SSH in. Add a new client by appending its `id_ed25519.pub` (or pasting
via `ssh-copy-id`).

## Client-side setup (any device that wants to SSH in)

1. Install `cloudflared`:
   - macOS: `brew install cloudflared`
   - Debian/Ubuntu: same Cloudflare apt repo as the server.

2. Add to `~/.ssh/config`:
   ```
   Host spark.huikang.dev
       User htong
       ProxyCommand cloudflared access ssh --hostname %h
   ```

3. Push the client's public key:
   ```bash
   ssh-copy-id -i ~/.ssh/id_ed25519.pub spark.huikang.dev
   ```
   (One-time; uses the existing key in `authorized_keys` to authenticate.
   On first setup when no key is present yet, this required temporarily
   enabling password auth.)

4. Connect: `ssh spark.huikang.dev`.

No Cloudflare Access policy is currently in front of the hostname — the
tunnel itself is the only gate, and SSH key auth is what enforces identity.
If multi-user access becomes a thing, add an Access self-hosted application
on `spark.huikang.dev` and require an email-domain policy.

## Operations

### View tunnel status

```bash
sudo systemctl status cloudflared
journalctl -u cloudflared -f
cloudflared tunnel info spark        # connector list, edge POPs
cloudflared tunnel ingress validate  # config sanity check
```

### Restart after config changes

```bash
sudo systemctl restart cloudflared
```

### Add another hostname through the same tunnel

Edit `/etc/cloudflared/config.yml`, add another `- hostname: ... service: ...`
block above the catch-all, then:
```bash
cloudflared tunnel route dns spark <new-hostname>
sudo systemctl restart cloudflared
```

### Tear down

```bash
sudo systemctl disable --now cloudflared
sudo cloudflared service uninstall
cloudflared tunnel delete spark   # also removes the DNS CNAME
sudo rm -rf /etc/cloudflared
rm -rf ~/.cloudflared
sudo apt-get remove --purge cloudflared
```

## Failure modes / debugging

- `ssh spark.huikang.dev` hangs at "Connecting to..." → `cloudflared` not on
  the SSH process's `$PATH`. Use absolute path in `ProxyCommand`
  (`/opt/homebrew/bin/cloudflared` on Apple Silicon, `/usr/local/bin/cloudflared`
  on Intel macOS / Linux).
- "Host key verification failed" → stale `~/.ssh/known_hosts` entry from a
  previous machine. `ssh-keygen -R spark.huikang.dev` then reconnect.
- "Permission denied (publickey)" with the right key on the laptop → either
  the wrong key was uploaded (check `~/.ssh/authorized_keys` `awk '{print $NF}'`
  for comments matching your laptop), or the home/`.ssh`/`authorized_keys`
  perms were loosened (must be `750` or stricter on `~`, `700` on `~/.ssh`,
  `600` on `authorized_keys`).
- Tunnel dies on Cloudflare's side → `journalctl -u cloudflared` will show
  reconnect attempts; the service auto-restarts and reopens four QUIC
  connections to the nearest edge POPs.
