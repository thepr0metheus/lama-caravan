#!/bin/bash
# The NVIDIA kernel guard (scripts/nvidia_kernel_guard.py) on an Ubuntu machine
# with an NVIDIA card and Secure Boot: after the automatic updates every
# installed kernel gets the card's signed modules, and GRUB boots the newest
# kernel that has them - a kernel installed without them is not booted.
# It also lets unattended-upgrade finish a driver series move (dpkg options):
# 2026-10-09 it skipped 610 -> 615 on a false conffile prompt, and the kernel
# it installed in the same run came up without the card.
#
#   install:   sudo bash scripts/install-nvidia-kernel-guard.sh
#   rollback:  sudo bash scripts/install-nvidia-kernel-guard.sh --uninstall
#   look:      nvidia-kernel-guard status   (as root: it reads grub.cfg)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
GUARD=/usr/local/sbin/nvidia-kernel-guard
DROPIN=/etc/systemd/system/apt-daily-upgrade.service.d/nvidia-kernel-guard.conf
HOOK=/etc/apt/apt.conf.d/99nvidia-kernel-guard
DPKG=/etc/apt/apt.conf.d/53unattended-upgrades-dpkg-options
GRUBDEF=/etc/default/grub
BACKUP=/etc/default/grub.before-nvidia-kernel-guard
[ "$(id -u)" = 0 ] || { echo "run as root: sudo bash $0 $*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$GUARD" "$DROPIN" "$HOOK" "$DPKG"
    rmdir "$(dirname "$DROPIN")" 2>/dev/null || true
    if [ -f "$BACKUP" ]; then cp -p "$BACKUP" "$GRUBDEF" && rm -f "$BACKUP"; fi
    grub-editenv /boot/grub/grubenv unset saved_entry || true
    systemctl daemon-reload
    update-grub
    echo "nvidia-kernel-guard removed: GRUB boots the newest kernel again"
    exit 0
fi

install -m 755 -o root -g root "$here/nvidia_kernel_guard.py" "$GUARD"

install -d -m 755 "$(dirname "$DROPIN")"
cat > "$DROPIN" <<EOF
# nvidia-kernel-guard: after the automatic updates, the card's signed modules for
# every kernel, then GRUB on the newest kernel that has them. Its failure is not
# the update's ("-").
[Service]
ExecStartPost=-$GUARD modules
EOF

cat > "$HOOK" <<EOF
// nvidia-kernel-guard: after every dpkg run GRUB boots the newest kernel that has
// the NVIDIA card's signed module; a kernel installed without one is not booted.
DPkg::Post-Invoke { "if [ -x $GUARD ]; then $GUARD boot || true; fi"; };
EOF

cat > "$DPKG" <<'EOF'
// nvidia-kernel-guard. The NVIDIA driver moves to a new series by renamed
// packages (610 -> 615, 2026-10-09). The new nvidia-kernel-common takes over a
// conffile of the old one; unattended-upgrade reads that as a conffile prompt
// and skips the whole series - and with it the signed modules of the kernel it
// installs in the same run. With --force-confold it does not skip such packages
// (dpkg_conffile_prompt() in /usr/bin/unattended-upgrade): dpkg keeps a file
// the admin changed and takes the package's version of one nobody changed.
Dpkg::Options {
   "--force-confdef";
   "--force-confold";
};
EOF
chmod 644 "$DROPIN" "$HOOK" "$DPKG"

# GRUB boots the entry the guard saves; until it saves one, the first - the newest kernel.
if ! grep -q '^GRUB_DEFAULT=saved$' "$GRUBDEF"; then
    cp -p "$GRUBDEF" "$BACKUP"
    if grep -q '^GRUB_DEFAULT=' "$GRUBDEF"; then
        sed -i 's/^GRUB_DEFAULT=.*/GRUB_DEFAULT=saved/' "$GRUBDEF"
    else
        echo 'GRUB_DEFAULT=saved' >> "$GRUBDEF"
    fi
    update-grub
fi

systemctl daemon-reload
"$GUARD" modules || true
"$GUARD" status
