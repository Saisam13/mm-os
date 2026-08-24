#!/usr/bin/env bash
# Generate the RSA-2048 signing keypair MM OS uses for RS256 (backend/app/security.py).
#
# Usage:
#   scripts/gen-signing-key.sh [PATH] [--force] [--kid KID]
#
#   PATH    where to write the private key PEM. Default: deploy/secrets/mmos_signing_key.pem
#           (the path deploy/docker-compose.yml's `secrets:` block expects on the host).
#   --force overwrite an existing key. Without it the script refuses and exits non-zero,
#           because overwriting the key invalidates every live session and service token —
#           every signed-in user gets kicked out and every service rejects every token still
#           in flight, all at once, with no warning.
#   --kid   the key id to print / suggest for MMOS_SIGNING_KEY_ID. Default: mmos-YYYY-MM
#           (matches the convention already in deploy/.env.example, e.g. mmos-2026-08).
#
# This only writes the PRIVATE key. backend/app/security.py derives the public JWKS from it
# at runtime (GET /.well-known/jwks.json) — there is nothing else to generate or distribute.
set -euo pipefail

KEY_PATH="deploy/secrets/mmos_signing_key.pem"
FORCE=0
KID="mmos-$(date +%Y-%m)"

while [ $# -gt 0 ]; do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        --kid)
            KID="${2:?--kid requires a value}"
            shift 2
            ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *)
            KEY_PATH="$1"
            shift
            ;;
    esac
done

if ! command -v openssl >/dev/null 2>&1; then
    echo "error: openssl not found on PATH — it is required to generate the key" >&2
    exit 1
fi

if [ -e "$KEY_PATH" ] && [ "$FORCE" -ne 1 ]; then
    echo "error: $KEY_PATH already exists." >&2
    echo "Overwriting it invalidates every live session and service token immediately." >&2
    echo "Re-run with --force only if you mean to rotate the key right now." >&2
    exit 1
fi

mkdir -p "$(dirname "$KEY_PATH")"

# PKCS#8 PEM, unencrypted (the file itself is the secret, protected by filesystem
# permissions and, in compose/Coolify, by being a mounted secret rather than an image
# layer or env var) — matches what backend/app/security.py's _load_or_create_key() reads
# with `serialization.load_pem_private_key(path.read_bytes(), password=None)`.
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$KEY_PATH" 2>/dev/null
chmod 600 "$KEY_PATH"

echo "Signing key written: $KEY_PATH (chmod 600)"
echo
echo "Set this in your env (deploy/.env or Coolify's env vars):"
echo "  MMOS_SIGNING_KEY_ID=$KID"
echo
echo "MMOS_SIGNING_KEY_PATH should already point at where this file is mounted inside the"
echo "container (default /run/secrets/mmos_signing_key.pem) — see deploy/docker-compose.yml."
