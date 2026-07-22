# Full Match message Relay over WebSocket

Players connect through an operator-owned WebSocket Relay that tracks Match membership and forwards Host↔Guest messages. We rejected peer-to-peer (WebRTC/NAT hole punching) because cross-city reliability and pasteable Invites matter more than avoiding a short-lived VM, and rejected Docker as the deploy model in favour of uv + Caddy + systemd on any SSH-able Linux host (provisioning lands in a later ticket). The Relay must stay dumb: no Boards, Fleets, or Shot resolution.
