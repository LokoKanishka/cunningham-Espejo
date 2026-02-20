#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_ROOT="${ROOT_DIR}/DOCS/HOST_AUDIT"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${AUDIT_ROOT}/${TS}"
LATEST_FILE="${AUDIT_ROOT}/LATEST"

mkdir -p "${OUT_DIR}"

run_cmd() {
  local name="$1"
  shift
  local outfile="${OUT_DIR}/${name}.txt"
  {
    echo "# ${name}"
    echo "# generated_at=$(date -Is)"
    echo "# cmd=$*"
    echo
    if command -v "$1" >/dev/null 2>&1; then
      "$@"
    else
      echo "command_not_found: $1"
    fi
  } >"${outfile}" 2>&1 || true
}

run_shell() {
  local name="$1"
  local cmd="$2"
  local outfile="${OUT_DIR}/${name}.txt"
  {
    echo "# ${name}"
    echo "# generated_at=$(date -Is)"
    echo "# shell=${cmd}"
    echo
    bash -lc "${cmd}"
  } >"${outfile}" 2>&1 || true
}

run_cmd date date -Is
run_cmd uname uname -a
run_cmd whoami whoami
run_cmd id id
run_cmd pwd pwd
run_cmd hostname hostname
run_cmd hostnamectl hostnamectl
run_cmd os_release cat /etc/os-release
run_cmd uptime uptime
run_cmd timedatectl timedatectl
run_cmd locale locale
run_shell env_redacted "env | LC_ALL=C sort | sed -E 's/(TOKEN|KEY|SECRET|PASSWORD|PASS|COOKIE)=.*/\\1=<redacted>/Ig'"

run_cmd lscpu lscpu
run_shell cpuinfo "cat /proc/cpuinfo"
run_cmd meminfo cat /proc/meminfo
run_cmd free free -h
run_shell vmstat "vmstat -s"

run_cmd lsblk lsblk -a -f
run_cmd blkid blkid
run_cmd df df -hT
run_shell mounts "cat /proc/mounts"

run_cmd ip_addr ip addr show
run_cmd ip_route ip route show
run_cmd ss_listen ss -tulpn
run_cmd resolv_conf cat /etc/resolv.conf
run_cmd hosts_file cat /etc/hosts
run_cmd nmcli_general nmcli general status
run_cmd nmcli_devices nmcli device status
run_cmd nmcli_connections nmcli connection show

run_cmd lspci lspci -nnk
run_cmd lsusb lsusb
run_cmd nvidia_smi nvidia-smi
run_cmd glxinfo glxinfo -B
run_cmd vulkaninfo vulkaninfo --summary

run_cmd pactl_info pactl info
run_cmd pactl_sources pactl list short sources
run_cmd pactl_sinks pactl list short sinks

run_cmd python3_version python3 --version
run_cmd pip3_version pip3 --version
run_cmd node_version node --version
run_cmd npm_version npm --version
run_cmd git_version git --version
run_cmd docker_version docker --version
run_cmd docker_compose_version docker compose version
run_cmd docker_ps docker ps -a
run_cmd docker_images docker images
run_cmd systemctl_user systemctl --user list-units --type=service --state=running --no-pager
run_cmd systemctl_system systemctl list-units --type=service --state=running --no-pager

run_shell apt_installed "dpkg-query -W -f='\${Package}\\t\${Version}\\n' | LC_ALL=C sort"
run_shell snap_list "snap list"
run_shell pip_freeze "python3 -m pip freeze"
run_shell npm_global "npm ls -g --depth=0"

run_shell repo_git_status "cd '${ROOT_DIR}' && git status --short --branch"
run_shell repo_git_remote "cd '${ROOT_DIR}' && git remote -v"
run_shell repo_tree "cd '${ROOT_DIR}' && find . -maxdepth 3 -type d | LC_ALL=C sort"

cat >"${OUT_DIR}/README.md" <<EOT
# Host Audit Snapshot

- Generated: $(date -Is)
- Host: $(hostname)
- User: $(whoami)
- Purpose: local machine context for DC/CUN operations.

Important:
- This snapshot is intentionally broad.
- Secrets in environment variable values are redacted in env output.
EOT

echo "${TS}" >"${LATEST_FILE}"

cat >"${AUDIT_ROOT}/README.md" <<'EOT'
# Host Audit Index

This folder stores machine context snapshots used by DC/CUN runtime operations.

- `LATEST`: timestamp of the newest snapshot.
- `<timestamp>/`: full snapshot files.

Generate a new snapshot:

```bash
./scripts/host_audit_full.sh
```
EOT

echo "host_audit_snapshot=${TS}"
