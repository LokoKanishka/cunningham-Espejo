# Host Audit Index

This folder stores machine context snapshots used by DC/CUN runtime operations.

- `LATEST`: timestamp of the newest snapshot.
- `<timestamp>/`: full snapshot files.

Generate a new snapshot:

```bash
./scripts/host_audit_full.sh
```
