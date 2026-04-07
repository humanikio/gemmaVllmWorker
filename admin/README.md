# Admin

Internal references for the Synthcore team. Do not commit secrets here.

## RunPod Access

| Item | Location |
|------|----------|
| API key config | `~/.runpod/config.toml` |
| SSH private key | `~/.runpod/ssh/RunPod-Key-Go` |
| SSH public key | `~/.runpod/ssh/RunPod-Key-Go.pub` |

These are generated per-developer by `runpodctl doctor`. Each team member has their own key pair — they are not shared.

The SSH public key is automatically uploaded to RunPod's cloud when generated, so any pod you create will accept your key.

### SSH Notes

The RunPod-Key-Go is an RSA key. Modern SSH clients (macOS Ventura+, OpenSSH 8.8+) disable `ssh-rsa` signatures by default. You must explicitly allow it:

```bash
ssh -o PubkeyAcceptedAlgorithms=+ssh-rsa <pod-id>@ssh.runpod.io -i ~/.runpod/ssh/RunPod-Key-Go
```

RunPod's SSH gateway also requires a PTY — non-interactive commands (`ssh host "command"`) fail with `Your SSH client doesn't support PTY`. Use `-tt` to force a TTY:

```bash
ssh -tt -o PubkeyAcceptedAlgorithms=+ssh-rsa <pod-id>@ssh.runpod.io -i ~/.runpod/ssh/RunPod-Key-Go "command"
```

Or add to `~/.ssh/config` to avoid repeating flags:

```
Host *.runpod.io
  PubkeyAcceptedAlgorithms +ssh-rsa
  RequestTTY force
  IdentityFile ~/.runpod/ssh/RunPod-Key-Go
```

## Network Volume

| Item | Value |
|------|-------|
| Volume ID | `yy1nhqfvtk` |
| Name | `gemma-models` |
| Size | 30GB |
| Datacenter | US-NC-1 |
| Mount path | `/workspace` |
| Model path | `/workspace/models/` |

Model weights are downloaded on first boot by `boot_model.py` and persist on the NVMe volume across pod stop/resume/recreate. No manual pre-download needed.

## Guides

- [RunPod CLI + SSH Dev Flow](../docs/guides/runpod-ssh-dev-flow.md) — How to spin up a GPU pod, SSH in, and test the worker
