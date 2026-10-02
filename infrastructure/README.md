# SpinSci EC2 Infrastructure (CDK)

AWS CDK (TypeScript) app that provisions a **single EC2 host** running the
existing SpinSci `docker-compose.yaml` stack, plus a GitHub Actions
**Deploy_Pipeline** (`.github/workflows/deploy-ec2.yml`) that ships each release
to the host over AWS Systems Manager (SSM) Run Command — no inbound SSH, no
static AWS keys.

This project provisions infrastructure only. The Docker build/push pipeline
(`docker-image.yml`), the compose runtime, and the `scripts/setup_remote.sh` /
`scripts/update_remote.sh` provisioning scripts are reused unchanged.

## What gets provisioned

- **VPC** (new, or an existing one imported by id) with one public subnet, an
  internet gateway, and no NAT gateway.
- **Security group** opening only 80, 443, 3478 (TCP+UDP), 5349 (TCP+UDP), and
  49152–49200 (UDP). **No port 22** — administrative shell access is via SSM
  Session Manager.
- **One EC2 instance** (default `t3.large`, Ubuntu 22.04) with an SSM instance
  profile and a cloud-init UserData that hands off to `setup_remote.sh`.
- **One Elastic IP** associated with the instance (the stable public address).
- **One EBS data volume** (gp3, encrypted, `RETAIN`) holding the Docker
  data-root and `.env`, attached at `/dev/sdf`, backed up by a **daily DLM
  snapshot policy** (7 retained).
- **IAM**: the SSM instance role/profile, a GitHub **OIDC provider**, and an
  **OIDC deploy role** scoped to this repo with least-privilege
  `ssm:SendCommand` + read permissions.

Stack outputs: `PublicIp`, `InstanceId`, `DataVolumeId`, `DeployRoleArn`.

## Prerequisites

- Node 22+, the AWS CDK CLI (`npm i -g aws-cdk`), and the AWS CLI v2.
- AWS credentials for the target account. For this project use the
  `032398581868_Developer` profile; deploy region is **us-east-2**.

```bash
cd infrastructure
npm ci
```

## Required inputs

Provided as CDK context (via `cdk.json` defaults, `-c key=value`, or
`--context`). Inputs with no default halt synthesis if missing.

| Input               | Context key          | Default                  | Required |
| ------------------- | -------------------- | ------------------------ | -------- |
| AWS region          | `region`             | — (or `CDK_DEFAULT_REGION`) | yes   |
| Public domain/host  | `host`               | —                        | yes      |
| GitHub repo         | `githubRepo`         | `sdpolke/voiceagent_v2` (cdk.json) | yes |
| Enable CI/CD role   | `enableDeployRole`   | `true`                   | no       |
| EC2 instance type   | `instanceType`       | `t3.large`               | no       |
| Data volume (GiB)   | `dataVolumeSizeGiB`  | `100` (1–16384)          | no       |
| Existing VPC id     | `vpcId`              | — (creates a new VPC)    | no       |
| Existing EIP alloc  | `eipAllocationId`    | — (allocates a new EIP)  | no¹      |
| Existing EIP address| `eipPublicIp`        | —                        | no¹      |
| Certificate mode    | `certMode`           | `auto`                   | no       |
| Deploy mode         | `deployMode`         | `prebuilt`               | no       |
| Let's Encrypt email | `letsEncryptEmail`   | —                        | no       |
| OIDC provider ARN   | `oidcProviderArn`    | — (creates the provider) | no       |

¹ `eipAllocationId` and `eipPublicIp` must be supplied together. When set, the
stack associates that existing Elastic IP and creates no new one; when omitted,
it allocates a fresh EIP. Reuse an existing EIP when the address is already
chosen (e.g. a DNS record points at it).

## Deploy the stack

```bash
export AWS_PROFILE=032398581868_Developer

# First time in this account/region only:
cdk bootstrap aws://032398581868/us-east-2

# Review, then deploy:
cdk synth  -c region=us-east-2 -c host=voice.example.com
cdk diff   -c region=us-east-2 -c host=voice.example.com
cdk deploy -c region=us-east-2 -c host=voice.example.com
```

After deploy, copy the stack outputs into the repo's Actions **variables** (not
secrets — none are sensitive) so the Deploy_Pipeline can find them:

- `DEPLOY_ROLE_ARN` ← `DeployRoleArn`
- `INSTANCE_ID` ← `InstanceId`
- `PUBLIC_HOST` ← your `host`

### First local deploy (CI/CD deferred)

For an initial deploy from a laptop before GitHub CI/CD is set up — and when the
deploying principal cannot create an IAM OIDC provider (e.g. a scoped SSO role in
a shared account) — disable the deploy role and deploy into an existing VPC:

```bash
cd infrastructure
export AWS_PROFILE=032398581868_Developer
cdk deploy \
  -c region=us-east-2 \
  -c host=voiceai.dev.voicelens.agenta-cloud.com \
  -c vpcId=vpc-01291b26806e0b4d8 \
  -c eipAllocationId=eipalloc-053f7e87eb3322f98 \
  -c eipPublicIp=3.18.59.28 \
  -c certMode=self-signed \
  -c enableDeployRole=false
```

`enableDeployRole=false` skips the GitHub OIDC provider and the deploy role
entirely (no `iam:CreateOpenIDConnectProvider` needed). Turn it back on later
(and pass `-c oidcProviderArn=<arn>` if a provider already exists in the account)
when wiring up CI/CD. DNS and TLS are handled separately — see "DNS / routing".

Do **not** run `cdk bootstrap` if the account already has a `CDKToolkit` stack.

### DNS / routing (manual — not managed by this stack)

This CDK stack creates **no Route 53 records**. After deploy, point your
subdomain at the Elastic IP from the `PublicIp` output. For a plain EIP (not an
ELB) create a **simple A record** (Alias: off) in the existing hosted zone:

```bash
aws route53 change-resource-record-sets \
  --profile 032398581868_Developer \
  --hosted-zone-id <HOSTED_ZONE_ID> \
  --change-batch '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"voiceai.dev.voicelens.agenta-cloud.com","Type":"A","TTL":300,
    "ResourceRecords":[{"Value":"<PublicIp>"}]}}]}'
```

Deploy with `certMode=self-signed` (or `sslip`) first; once the A record
resolves, switch to `certMode=auto` so Let's Encrypt can issue a real cert.

## Release deploy (automatic)

When a GitHub release is published, `deploy-ec2.yml`:

1. resolves the release tag,
2. **gates** on Docker Hub image availability (fails naming the tag if the
   images are not published — no SSM command is issued),
3. assumes the OIDC role (short-lived creds; no static keys),
4. checks the instance is an Online SSM managed instance,
5. sends one `AWS-RunShellScript` command that runs `update_remote.sh` then
   `remote_up.sh` with `TARGET_VERSION=<tag>` and `SPINSCI_UPDATE_YES=1`,
6. records the SSM `CommandId` + stdout/stderr to the job summary,
7. polls `https://<host>/api/v1/health` until `status: ok` or the timeout,
8. reports success/failure naming the tag.

## Rollback / deploy an older version (manual)

Rollback uses the same SSM path with an explicitly selected tag:

1. Actions → **Deploy to EC2 (SSM)** → **Run workflow**.
2. Set `tag` to the older released tag (e.g. `spinsci-v1.27.0`) and optionally
   `health_timeout` (30–600s, default 120).

The pipeline deploys exactly that tag — it never substitutes a newer one. The
data volume and `.env` secrets are untouched by a rollback. **No automatic
rollback is ever performed** on a failed deploy; the host is left running its
current state for inspection.

## Backups: snapshot & restore

**Automatic:** the DLM policy snapshots the data volume daily (03:00 UTC) and
retains the last 7, targeting the volume by its `spinsci:data-volume=true` tag.

**On-demand snapshot** (for stronger Postgres consistency, briefly stop the DB
first):

```bash
export AWS_PROFILE=032398581868_Developer
# optional, on the host: docker compose stop postgres
aws ec2 create-snapshot --region us-east-2 \
  --volume-id <DataVolumeId> \
  --description "spinsci manual $(date -u +%FT%TZ)"
```

**Restore from a snapshot** (volume and instance must share an AZ):

```bash
AZ="$(aws ec2 describe-instances --region us-east-2 \
  --instance-ids <InstanceId> \
  --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text)"

NEW_VOL="$(aws ec2 create-volume --region us-east-2 \
  --snapshot-id <SnapshotId> --availability-zone "$AZ" \
  --volume-type gp3 --query 'VolumeId' --output text)"

# Detach the current data volume, then attach the restored one at the same device:
aws ec2 detach-volume --region us-east-2 --volume-id <DataVolumeId>
aws ec2 attach-volume --region us-east-2 \
  --volume-id "$NEW_VOL" --instance-id <InstanceId> --device /dev/sdf
```

Reboot the instance (or re-run the UserData mount logic). Because the deploy dir
+ `.env` and the Docker data-root both live on the volume, the restored volume
brings back both application data and secrets together.

## External credentials via AWS Secrets Manager

External third-party API keys (Cartesia, Groq, Deepgram, OpenAI, Langfuse,
PostHog, Sentry, ...) are **not** stored in the image or committed anywhere.
They live in **one Secrets Manager secret** and are fetched at **container
start** by `scripts/fetch_secrets.sh` using the EC2 instance role.

Box-internal secrets (`OSS_JWT_SECRET`, DB/Redis/MinIO passwords, `TURN_SECRET`)
are **not** in Secrets Manager — `setup_remote.sh` still generates those locally
into `.env` on the data volume, where they persist and never leave the host.

> Secrets are fetched at RUNTIME, never baked at build time. Anything baked into
> an image layer is readable by anyone who can pull the image.

### 1. Create the secret (operator, one-time)

Store a flat JSON object — each top-level key becomes an environment variable:

```bash
export AWS_PROFILE=032398581868_Developer
aws secretsmanager create-secret --region us-east-2 \
  --name spinsci/prod/app \
  --secret-string '{
    "CARTESIA_API_KEY": "...",
    "GROQ_API_KEY": "...",
    "DEEPGRAM_API_KEY": "...",
    "OPENAI_API_KEY": "...",
    "LANGFUSE_SECRET_KEY": "...",
    "POSTHOG_API_KEY": "...",
    "SENTRY_DSN": "..."
  }'
# Note the returned COMPLETE ARN (ends with a 6-char suffix, e.g. ...-AbCdEf).
```

### 2. Point the stack at it

Pass the complete ARN as context on deploy. The stack imports it (secret
material never enters CloudFormation) and grants **only the instance role**
least-privilege `secretsmanager:GetSecretValue` on that ARN:

```bash
cdk deploy -c region=us-east-2 -c host=voice.example.com \
  -c appSecretArn=arn:aws:secretsmanager:us-east-2:032398581868:secret:spinsci/prod/app-AbCdEf
```

If the secret is encrypted with a **customer-managed KMS key** (recommended for
prod), also pass `-c kmsKeyArn=arn:aws:kms:us-east-2:032398581868:key/<id>`; the
instance role then also gets `kms:Decrypt` scoped to that key. With the
AWS-managed `aws/secretsmanager` key, no KMS input is needed.

When `appSecretArn` is omitted the whole integration is inert — no Secrets
Manager permission is attached and the app uses `.env` only.

### 3. How it resolves at runtime

On first boot, UserData writes **only the ARN + region** (never the value) to
`/mnt/spinsci-data/spinsci/.spinsci-secret-ref.env` (mode 600). The container
entrypoint `scripts/fetch_secrets.sh` reads that reference, calls
`GetSecretValue` via the instance role, exports each JSON key into the process
environment, and `exec`s the app — so the existing `os.getenv(...)` reads work
unchanged. Values are never logged, never written to disk, and never passed as
compose `environment:` or build args.

To wire it as the container entrypoint, prefix the app command, e.g.
`["/app/scripts/fetch_secrets.sh", "python", "-m", "api"]`.

### Rotation

Rotate the key at the provider, update the secret
(`aws secretsmanager put-secret-value ...`), then restart the stack
(`./remote_up.sh` on the host, or redeploy). The entrypoint re-fetches on start.
Access is auditable via CloudTrail `GetSecretValue` events.

### Security model

- Resource-scoped `GetSecretValue` on the exact secret ARN — never `*`.
- Grant is on the **instance role only**; the GitHub OIDC deploy role has **no**
  secret access (it only issues SSM commands).
- Secret material never enters the image, CloudFormation, git, or logs.

## Local commands

```bash
npm run build      # tsc
npm test           # vitest (unit + property tests)
npm run synth      # cdk synth
```
