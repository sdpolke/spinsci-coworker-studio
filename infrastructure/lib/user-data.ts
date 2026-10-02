import { CertMode, DeployMode } from './props';

/**
 * Pure cloud-init / UserData text builder for the SpinSci EC2 instance.
 *
 * This module is deliberately a PURE string builder: it takes a typed config
 * object and returns the cloud-init shell text. It constructs no CDK resources
 * and performs no I/O, so the property tests (task 6.2/6.3) can assert on the
 * generated text directly without a synth.
 *
 * Responsibilities (Req 3.1–3.6, 6.2, 7.2, 7.4):
 *  - Resolve the Data_Volume's actual block device by matching the EBS volume
 *    id (NVMe-safe) rather than hard-coding `/dev/xvdf`, then mount it at
 *    `/mnt/spinsci-data` and persist the mount in `/etc/fstab`.
 *  - Relocate Docker's data-root to `/mnt/spinsci-data/docker` via
 *    `/etc/docker/daemon.json` BEFORE Docker starts, so every compose named
 *    volume (postgres/redis/minio/...) lands on the persistent volume (Req 6.2).
 *  - Place the deploy dir (`spinsci/`, holding `.env`) on the volume (Req 7.2).
 *  - Export the setup contract env vars (`SERVER_IP`, `CERT_MODE`,
 *    `DEPLOY_MODE`, `FASTAPI_WORKERS`, `LETSENCRYPT_EMAIL`) and invoke the
 *    existing `scripts/setup_remote.sh` as root, non-interactively (Req 3.1–3.4).
 *  - NEVER pass `SPINSCI_FORCE_OVERWRITE`, so an existing `.env` on the volume
 *    is preserved and the first-boot secret path is not re-run (Req 7.4).
 *  - Reimplement NONE of the Docker-install / secret-gen / cert-issue / stack
 *    -start logic — that all lives in the reused scripts (Req 3.5).
 */

/** Mount point for the persistent Data_Volume. */
export const DATA_MOUNT_POINT = '/mnt/spinsci-data';

/** Docker data-root, relocated onto the Data_Volume (Req 6.2). */
export const DOCKER_DATA_ROOT = `${DATA_MOUNT_POINT}/docker`;

/** The deploy dir created by first-boot setup; holds `.env` + compose files (Req 7.2). */
export const DEPLOY_DIR = `${DATA_MOUNT_POINT}/spinsci`;

/**
 * Typed input to {@link buildUserData}. Mirrors the subset of
 * `SpinSciEc2StackProps` the bootstrap needs, plus the two runtime values only
 * known once the stack is composed (the volume id to resolve the device, and
 * the repo to clone the deploy bundle from).
 */
export interface UserDataConfig {
  /**
   * The EBS Data_Volume id (e.g. `vol-0abc…`). UserData matches this against
   * the NVMe/`lsblk` serial to find the real device, since the kernel may
   * surface `/dev/sdf` as `/dev/xvdf` or an NVMe alias.
   */
  readonly dataVolumeId: string;

  /**
   * The Elastic_IP, forwarded to the setup script as `SERVER_IP` (Req 3.3).
   */
  readonly serverIp: string;

  /** Certificate mode forwarded as `CERT_MODE` (Req 3.4). */
  readonly certMode: CertMode;

  /** Deploy mode forwarded as `DEPLOY_MODE` (Req 3.4). */
  readonly deployMode: DeployMode;

  /** Optional Let's Encrypt contact email forwarded as `LETSENCRYPT_EMAIL`. */
  readonly letsEncryptEmail?: string;

  /** Non-interactive FastAPI worker count. Defaults to 2 (setup's own default). */
  readonly fastapiWorkers?: number;

  /**
   * The git repository (`owner/name`) to clone the deploy bundle from on first
   * boot. Defaults to the SpinSci repo slug.
   */
  readonly repo: string;

  /** Git ref to check out for the deploy bundle. Defaults to `main`. */
  readonly repoRef?: string;

  /**
   * Complete ARN of the Secrets Manager secret holding external credentials.
   * When set, UserData records it in the deploy dir so the container entrypoint
   * (`scripts/fetch_secrets.sh`) resolves it at RUNTIME via the instance role.
   * When omitted, the secret fetch stays inert and the app uses `.env` only.
   * The value is only an ARN reference — never the secret material.
   */
  readonly appSecretArn?: string;

  /** Region for the Secrets Manager API call (the stack's deploy region). */
  readonly secretRegion?: string;
}

/**
 * Shell-escape a value for safe single-quoted embedding. Wraps in single
 * quotes and escapes any embedded single quote. Keeps operator-supplied values
 * (host, email, repo) from breaking out of the generated script.
 */
function sq(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * Build the cloud-init UserData script text for the SpinSci instance.
 *
 * The returned string is a `#!/bin/bash` script run once as root by cloud-init
 * on first boot. It is idempotent with respect to an existing `.env`: because
 * it never sets `SPINSCI_FORCE_OVERWRITE`, `setup_remote.sh` refuses to
 * overwrite an existing `.env` and skips first-boot secret generation (Req 7.4).
 */
export function buildUserData(config: UserDataConfig): string {
  const workers = config.fastapiWorkers ?? 2;
  const repoRef = config.repoRef ?? 'main';
  const repoUrl = `https://github.com/${config.repo}.git`;

  // Optional email export line, only when supplied.
  const emailExport = config.letsEncryptEmail
    ? `export LETSENCRYPT_EMAIL=${sq(config.letsEncryptEmail)}`
    : '# LETSENCRYPT_EMAIL not supplied';

  // Optional Secrets Manager reference. We persist ONLY the ARN + region (never
  // secret material) into a reference file on the volume so the container
  // entrypoint (scripts/fetch_secrets.sh) can resolve the secret at runtime via
  // the instance role. When no ARN is configured, the fetch stays inert.
  const secretRefBlock = config.appSecretArn
    ? `# --- 4b. Record the app-secret reference for runtime fetch (NOT the secret) --
# scripts/fetch_secrets.sh reads these at container start and resolves the
# secret from Secrets Manager using the instance role. Only the ARN/region are
# written here — never the secret value, and never into the image.
cat > ${DEPLOY_DIR}/.spinsci-secret-ref.env <<REF
SPINSCI_APP_SECRET_ARN=${config.appSecretArn}
SPINSCI_SECRET_REGION=${config.secretRegion ?? ''}
REF
chmod 600 ${DEPLOY_DIR}/.spinsci-secret-ref.env`
    : '# No app secret configured; runtime secret fetch is inert.';

  return `#!/bin/bash
# SpinSci EC2 first-boot bootstrap (CDK UserData).
# Delegates all provisioning to scripts/setup_remote.sh — this script only
# prepares the persistent volume + env contract. (Req 3.1-3.6, 6.2, 7.2, 7.4)
set -euo pipefail
exec > >(tee -a /var/log/spinsci-userdata.log) 2>&1
echo "[spinsci] userdata start: $(date -u +%FT%TZ)"

# --- 1. Resolve the Data_Volume device by EBS volume id (NVMe-safe) ----------
# The kernel may surface the attachment as /dev/xvdf or an NVMe alias; match on
# the volume id serial rather than trusting a fixed device path.
VOL_ID=${sq(config.dataVolumeId)}
# NVMe serials drop the dash from the volume id (vol-0abc -> vol0abc).
VOL_ID_NODASH="\${VOL_ID//-/}"
DATA_DEV=""
for _ in $(seq 1 30); do
  for dev in $(lsblk -dpno NAME); do
    serial="$(nvme id-ctrl "$dev" 2>/dev/null | awk -F: '/^sn/{gsub(/ /,"",$2); print $2}')" || true
    if [ -z "$serial" ]; then
      serial="$(udevadm info --query=property --name="$dev" 2>/dev/null | sed -n 's/^ID_SERIAL_SHORT=//p')" || true
    fi
    case "$serial" in
      *"$VOL_ID_NODASH"*|*"$VOL_ID"*) DATA_DEV="$dev"; break 2 ;;
    esac
  done
  echo "[spinsci] waiting for data volume $VOL_ID to appear..."
  sleep 5
done
if [ -z "$DATA_DEV" ]; then
  echo "[spinsci] FATAL: could not resolve data volume $VOL_ID to a device" >&2
  exit 1
fi
echo "[spinsci] data volume $VOL_ID resolved to $DATA_DEV"

# --- 2. Format (first boot only) + mount at ${DATA_MOUNT_POINT} ---------------
# Only mkfs when the device has no filesystem, so an existing volume (and its
# data + .env) is never reformatted on instance replacement. (Req 6.4, 7.2)
if ! blkid "$DATA_DEV" >/dev/null 2>&1; then
  echo "[spinsci] no filesystem on $DATA_DEV; creating ext4 (first boot)"
  mkfs -t ext4 "$DATA_DEV"
fi
mkdir -p ${DATA_MOUNT_POINT}
DATA_UUID="$(blkid -s UUID -o value "$DATA_DEV")"
if ! grep -q "$DATA_UUID" /etc/fstab; then
  echo "UUID=$DATA_UUID ${DATA_MOUNT_POINT} ext4 defaults,nofail 0 2" >> /etc/fstab
fi
mount -a
mkdir -p ${DOCKER_DATA_ROOT} ${DEPLOY_DIR}

# --- 3. Relocate Docker data-root onto the volume BEFORE Docker starts -------
# Every compose named volume (postgres/redis/minio/...) then lands on the
# persistent Data_Volume. (Req 6.2)
mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json <<JSON
{ "data-root": "${DOCKER_DATA_ROOT}" }
JSON
fi

# --- 4. Fetch the deploy bundle onto the volume ------------------------------
# setup_remote.sh lives in the repo; clone it into the volume-backed deploy dir
# on first boot. On replacement the dir already exists with .env intact.
export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y git
fi
if [ ! -d ${DEPLOY_DIR}/.git ]; then
  git clone --depth 1 --branch ${sq(repoRef)} ${sq(repoUrl)} ${DEPLOY_DIR}
fi
cd ${DEPLOY_DIR}

${secretRefBlock}

# --- 5. Export the setup contract and hand off to setup_remote.sh ------------
# NOTE: SPINSCI_FORCE_OVERWRITE is intentionally NEVER set, so an existing .env
# on the volume is preserved and the first-boot secret path is skipped. (Req 7.4)
export SERVER_IP=${sq(config.serverIp)}
export CERT_MODE=${sq(config.certMode)}
export DEPLOY_MODE=${sq(config.deployMode)}
export FASTAPI_WORKERS=${sq(String(workers))}
${emailExport}

echo "[spinsci] handing off to scripts/setup_remote.sh (CERT_MODE=$CERT_MODE DEPLOY_MODE=$DEPLOY_MODE)"
# Run as root, non-interactive; -E preserves the exported contract. (Req 3.1, 3.2)
sudo -E bash ${DEPLOY_DIR}/scripts/setup_remote.sh
echo "[spinsci] userdata done: $(date -u +%FT%TZ)"
`;
}
