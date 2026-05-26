#!/usr/bin/env bash
# Update the Home Assistant local "Wine Tracker (Dev)" addon from GitHub main.
#
# Run inside the HA SSH addon console:
#   curl -fsSL https://raw.githubusercontent.com/xenofex7/ha-wine-tracker/main/scripts/update-ha-dev.sh | bash
#
# Workflow:
#   1. Clone/pull the repo to /tmp/ha-wine-tracker-repo (shallow)
#   2. rsync the wine-tracker/ subfolder into /addons/wine-tracker-dev/
#   3. Patch slug + name so HA treats this as a separate addon from
#      the official one installed via the addon store
#   4. Reload, rebuild, restart the addon

set -euo pipefail

REPO_URL="https://github.com/xenofex7/ha-wine-tracker.git"
REPO_DIR="/tmp/ha-wine-tracker-repo"
ADDON_DIR="/addons/wine-tracker-dev"
ADDON_SLUG="wine_tracker_dev"
ADDON_NAME="Wine Tracker (Dev)"

echo "==> Sync repo to $REPO_DIR"
if [ -d "$REPO_DIR/.git" ]; then
  git -C "$REPO_DIR" fetch --depth=1 origin main
  git -C "$REPO_DIR" reset --hard origin/main
else
  rm -rf "$REPO_DIR"
  git clone --depth=1 "$REPO_URL" "$REPO_DIR"
fi

echo "==> Copy wine-tracker/ -> $ADDON_DIR"
# rsync isn't installed in HA's SSH BusyBox, so wipe + cp -a instead.
# This is fine because the addon is stopped/rebuilt right after.
rm -rf "$ADDON_DIR"
mkdir -p "$ADDON_DIR"
cp -a "$REPO_DIR/wine-tracker/." "$ADDON_DIR/"

echo "==> Patch config.yaml (slug + name for dev variant)"
sed -i "s/^slug: .*/slug: \"$ADDON_SLUG\"/" "$ADDON_DIR/config.yaml"
sed -i "s/^name: .*/name: \"$ADDON_NAME\"/" "$ADDON_DIR/config.yaml"

echo "==> Reload + rebuild + restart addon"
# Newer HA versions print "addons is deprecated, please use apps instead!"
# but both still work; `ha apps` is preferred so we use that.
ha apps reload

if ha apps info "$ADDON_SLUG" >/dev/null 2>&1; then
  ha apps rebuild "$ADDON_SLUG" || true
  ha apps restart "$ADDON_SLUG" || true
  echo "==> Done. Open Wine Tracker (Dev) in HA."
else
  echo
  echo "==> First-time install detected."
  echo "    The addon is now visible in HA but not yet installed."
  echo "    Open: Settings -> Add-ons -> Add-on Store -> Local add-ons"
  echo "          -> Wine Tracker (Dev) -> Install"
  echo "    Future runs will rebuild + restart automatically."
fi
