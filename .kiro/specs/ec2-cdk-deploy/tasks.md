# Implementation Plan: EC2 CDK Deploy

## Overview

This plan implements the two gaps identified in the design: (1) an AWS CDK (TypeScript) app under `infrastructure/` that provisions a single EC2 host for the existing `docker-compose.yaml` stack, and (2) a new GitHub Actions workflow `.github/workflows/deploy-ec2.yml` that deploys releases via SSM Run Command using OIDC auth.

The existing tooling — `docker-image.yml`, `docker-compose.yaml`, `scripts/setup_remote.sh`, `scripts/update_remote.sh`, `remote_up.sh` — is reused unchanged. Tasks touch these only through wiring (UserData exports env vars for `setup_remote.sh`; the deploy workflow invokes `update_remote.sh`).

Work proceeds incrementally: scaffold the CDK project, build the constructs bottom-up (networking → storage → IAM → UserData text → compute), compose them into the stack, then author the deploy workflow's pure logic + YAML, and finally the operator runbook and `cdk synth` validation. Property-based tests (fast-check) and `aws-cdk-lib/assertions` unit tests are written adjacent to the code they cover.

## Tasks

- [x] 1. Scaffold the CDK project under `infrastructure/`
  - Create `infrastructure/` with `package.json` (aws-cdk-lib v2, constructs, fast-check, vitest, typescript, ts-node), `tsconfig.json`, and `cdk.json` (app command `npx ts-node --prefer-ts-exts bin/spinsci-ec2.ts`, context defaults for `instanceType=t3.large`, `dataVolumeSizeGiB=100`, `certMode=auto`, `deployMode=prebuilt`, `githubRepo`)
  - Create the directory skeleton: `bin/`, `lib/`, `test/`
  - Add a vitest config and an npm test script so `aws-cdk-lib/assertions` + fast-check tests run
  - _Requirements: 1.8_

- [x] 2. Define stack props and typed input contract
  - [x] 2.1 Create `lib/props.ts` with the `SpinSciEc2StackProps` interface
    - Encode fields: `host` (required), `instanceType`, `dataVolumeSizeGiB`, `vpcId?`, `certMode`, `deployMode`, `letsEncryptEmail?`, `githubRepo`, `oidcProviderArn?`
    - Add typed enums for `certMode` (`auto`|`sslip`|`self-signed`) and `deployMode` (`prebuilt`|`build`)
    - _Requirements: 1.3, 1.4, 1.6, 1.8, 3.4, 5.5_

- [ ] 3. Implement the networking construct
  - [x] 3.1 Create `lib/network-construct.ts`
    - Import VPC via `Vpc.fromLookup({ vpcId })` when `vpcId` is set (fail synth if imported VPC has no public subnet); else create a `Vpc` with 1 public subnet, `natGateways: 0`, `maxAzs: 1`
    - Create the Security_Group with `allowAllOutbound: true` and ingress: TCP 80, TCP 443, TCP+UDP 3478, TCP+UDP 5349, UDP 49152–49200 from `0.0.0.0/0`; add no port 22 rule
    - Expose the vpc, chosen public subnet, and security group for the compute construct
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 3.2 Write property test for the security group having no port 22
    - **Property 1: Security group never opens port 22**
    - **Validates: Requirements 2.5, 2.6, 4.3**
    - fast-check over random valid stack configs; synth and assert no ingress rule satisfies `FromPort <= 22 <= ToPort` for tcp or udp

  - [ ]* 3.3 Write unit tests for VPC create-vs-import and required ingress rules
    - Assert zero `AWS::EC2::VPC` when `vpcId` set, one otherwise
    - Assert each required ingress rule (TCP 80, TCP 443, TCP+UDP 3478/5349, UDP 49152–49200) is present
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4_

- [ ] 4. Implement the storage construct
  - [x] 4.1 Create `lib/storage-construct.ts`
    - Create a standalone `Volume` (gp3, `encrypted: true`, `size = dataVolumeSizeGiB`, in the instance AZ) with `removalPolicy: RETAIN` (DeletionPolicy + UpdateReplacePolicy Retain)
    - Tag the volume `spinsci:data-volume = true`; attach via a separate `CfnVolumeAttachment` at a deterministic device (`/dev/sdf`)
    - Create a DLM snapshot policy targeting the volume by tag (daily snapshots with a retention count)
    - Expose the volume id/ref so UserData can resolve the device by volume id
    - _Requirements: 1.6, 6.1, 6.2, 6.4, 6.5_

  - [ ]* 4.2 Write property test for volume RETAIN + standalone attachment
    - **Property 2: Data volume is never destroyed on stack update**
    - **Validates: Requirements 6.1, 6.4**
    - fast-check over random valid stack configs; synth and assert the `AWS::EC2::Volume` has DeletionPolicy/UpdateReplacePolicy Retain and is attached via a separate `VolumeAttachment` (not an inline block device)

  - [ ]* 4.3 Write property test for data volume size bounds
    - **Property 5: Data volume size is accepted only within bounds**
    - **Validates: Requirements 1.6**
    - fast-check over random integers; construct succeeds and produces a volume of exactly that size when in `[1, 16384]`, and throws a validation error naming the bound when outside

  - [ ]* 4.4 Write unit test for the DLM backup policy targeting the volume
    - Assert a DLM lifecycle policy exists and targets the volume by the `spinsci:data-volume` tag
    - _Requirements: 6.5_

- [ ] 5. Implement the IAM construct
  - [x] 5.1 Create `lib/iam-construct.ts` instance role + profile
    - Create an IAM `Role` with `ServicePrincipal('ec2.amazonaws.com')` and managed policy `AmazonSSMManagedInstanceCore`; wrap in an `InstanceProfile`
    - Expose the instance profile for the compute construct
    - _Requirements: 1.7_

  - [x] 5.2 Add the GitHub OIDC provider and OIDC_Role
    - Create an `OpenIdConnectProvider` for `https://token.actions.githubusercontent.com` (audience `sts.amazonaws.com`), or import by `oidcProviderArn` when supplied
    - Create the OIDC_Role assumed via web identity with a trust policy scoping `:sub` to `repo:<githubRepo>:*` and `:aud` to `sts.amazonaws.com`
    - Attach a least-privilege inline policy: `ssm:SendCommand` scoped to the instance ARN + `AWS-RunShellScript` document ARN; `ssm:GetCommandInvocation`/`ListCommandInvocations`/`ListCommands`; optional `ssm:DescribeInstanceInformation`/`ec2:DescribeInstanceInformation`; no `iam:PassRole`, no wildcard admin, no static keys
    - Output the OIDC_Role ARN as a stack output
    - _Requirements: 5.2, 5.4, 5.5_

  - [ ]* 5.3 Write property test for OIDC trust scoped to the repo
    - **Property 3: OIDC trust matches only the SpinSci repository**
    - **Validates: Requirements 5.5**
    - fast-check over random `githubRepo` values; synth and assert trust `:sub` binds `repo:<githubRepo>:*` and `:aud` is `sts.amazonaws.com`

  - [ ]* 5.4 Write property test for OIDC role least privilege
    - **Property 4: OIDC role grants only SSM send-and-read permissions**
    - **Validates: Requirements 5.4**
    - fast-check over random valid stack configs; synth and assert every granted action is in the allowed set, `ssm:SendCommand` is resource-scoped to the instance + document ARNs, and no statement grants wildcard admin / `iam:PassRole` / any write beyond `SendCommand`

- [ ] 6. Implement the UserData builder
  - [x] 6.1 Create `lib/user-data.ts` as a pure cloud-init text builder
    - Build cloud-init text that: resolves the Data_Volume device by matching the EBS volume id (via `nvme`/`lsblk`), mounts it at `/mnt/spinsci-data`, relocates Docker data-root to `/mnt/spinsci-data/docker` via `/etc/docker/daemon.json` before Docker starts, and places the deploy dir on the volume
    - Fetch the deploy bundle/repo and export `SERVER_IP` (the Elastic IP), `CERT_MODE`, `DEPLOY_MODE`, `FASTAPI_WORKERS`, `LETSENCRYPT_EMAIL`, then run `setup_remote.sh` as root non-interactively
    - Never pass `SPINSCI_FORCE_OVERWRITE`; skip the first-boot secret path when `.env` already exists (idempotent); reimplement none of the docker/secret/cert logic
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 6.2, 7.2, 7.4_

  - [ ]* 6.2 Write property test for UserData forwarding cert/deploy mode exactly
    - **Property 11: UserData forwards certificate and deploy mode exactly**
    - **Validates: Requirements 3.4**
    - fast-check over `certMode` × `deployMode` enum combinations; assert the generated text exports `CERT_MODE` and `DEPLOY_MODE` equal to the props

  - [ ]* 6.3 Write property test for UserData `.env` idempotence
    - **Property 10: UserData never overwrites an existing .env (idempotence)**
    - **Validates: Requirements 7.4**
    - fast-check over prior `.env` states; assert the bootstrap decision never emits `SPINSCI_FORCE_OVERWRITE` and does not trigger the first-boot secret path when `.env` exists
    - Note: full container-level secret preservation (Req 7.3, 7.5, 8.5 / Properties 9) is integration/manual, not a unit property — see integration notes

  - [ ]* 6.4 Write unit test asserting UserData delegates rather than reimplements
    - Assert the text invokes `setup_remote.sh` as root non-interactively, exports `SERVER_IP`, sets Docker data-root under the mount, places the deploy dir on the mount, and contains no docker-install/secret-gen/cert-issue logic
    - _Requirements: 3.1, 3.2, 3.3, 3.5, 3.6, 6.2, 7.2_

- [ ] 7. Implement the compute construct
  - [x] 7.1 Create `lib/compute-construct.ts`
    - Resolve the Ubuntu 22.04 LTS (amd64) AMI via `MachineImage.fromSsmParameter` on the Canonical public SSM parameter
    - Create exactly one `Instance` of `instanceType` (default `t3.large`) in the public subnet, with the security group, the instance profile, and the UserData from `lib/user-data.ts`
    - Create one `CfnEIP` + `CfnEIPAssociation` bound to the instance; output the associated address as `PublicIp` and use it as `SERVER_IP` in UserData
    - _Requirements: 1.3, 1.4, 1.5, 3.3_

  - [ ]* 7.2 Write unit tests for the instance, instance type, and Elastic IP
    - Assert exactly one `AWS::EC2::Instance` with `InstanceType` equal to input/default, one `AWS::EC2::EIP` + association referencing the instance, and the instance role has `AmazonSSMManagedInstanceCore`
    - _Requirements: 1.3, 1.4, 1.5, 1.7_

- [ ] 8. Compose the stack and app entrypoint with input validation
  - [x] 8.1 Create `lib/spinsci-ec2-stack.ts`
    - Instantiate the networking, storage, IAM, and compute constructs and wire them together (SG + profile + UserData into the instance; volume attachment to the instance; EIP association)
    - Surface stack outputs (`PublicIp`, OIDC_Role ARN, instance id)
    - _Requirements: 1.1, 1.5, 1.7, 5.4_

  - [x] 8.2 Create `bin/spinsci-ec2.ts` entrypoint with required-input validation
    - Read context/props; validate presence of `region` and `host` (no defaults) before instantiating the stack; validate `dataVolumeSizeGiB` in `[1, 16384]` and `certMode`/`deployMode` against enums
    - On a missing/invalid required input, throw an error naming the input and exit non-zero so no resources are synthesized
    - _Requirements: 1.8, 1.9_

  - [ ]* 8.3 Write property test for missing required input halting synthesis
    - **Property 6: Missing required input halts synthesis naming the input**
    - **Validates: Requirements 1.9**
    - fast-check over the required inputs (`region`, `host`); omitting each causes construction/synth to throw an error whose message contains the input name and produces no template

- [ ] 9. Checkpoint - CDK constructs and stack
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. Implement the deploy pipeline's pure logic
  - [x] 10.1 Create the shared deploy-logic helper (`.github/workflows/lib/deploy_lib.sh` and/or a tiny Node module the workflow and tests both call)
    - Implement pure functions: resolve tag → `TARGET_VERSION` (identity, no substitution), image-availability gate, SSM parameter build, health predicate (`isHealthy`), the health poller (fixed interval, injected clock + fetch), and timeout resolution (bounds + default)
    - Keep the tested code identical to the code the workflow invokes
    - _Requirements: 4.2, 4.5, 8.1, 8.2, 8.3, 9.1, 9.2, 9.3, 9.4_

  - [ ]* 10.2 Write property test for TARGET_VERSION identity
    - **Property 7: The deployed target version is exactly the selected tag**
    - **Validates: Requirements 4.2, 8.1, 8.2**
    - fast-check over random tag strings (including an older tag and a literal `latest`); assert the SSM params set `TARGET_VERSION` to exactly that tag, never substituting

  - [ ]* 10.3 Write property test for the image-availability gate
    - **Property 8: Deploy is gated on image availability**
    - **Validates: Requirements 4.5, 8.3**
    - fast-check over random tags + a registry-present flag; when absent the gate issues no command and fails naming the tag, when present the gate permits the send

  - [ ]* 10.4 Write property test for the health predicate
    - **Property 12: Health is recognized only on a successful healthy response**
    - **Validates: Requirements 9.2**
    - fast-check over random (status, body, error) triples; `isHealthy` is true iff a 2xx healthy response, otherwise false

  - [ ]* 10.5 Write property test for the health poller
    - **Property 13: The health poller stops on first healthy response or fails at timeout**
    - **Validates: Requirements 9.1, 9.4**
    - fast-check over random response sequences + timeouts in `[30, 600]` with injected fake clock/fetch; poller queries at a fixed interval in `[5, 30]`, returns success on first healthy response, fails once timeout elapses

  - [ ]* 10.6 Write property test for timeout resolution
    - **Property 14: Health-check timeout resolution respects bounds and default**
    - **Validates: Requirements 9.3**
    - fast-check over random ints incl. undefined; resolved timeout equals input when in `[30, 600]`, rejects out-of-range with a validation error, and defaults to `120` when unset

- [ ] 11. Author the deploy workflow YAML (`.github/workflows/deploy-ec2.yml`)
  - [x] 11.1 Create the workflow wiring the pure logic to real steps
    - Triggers: `release: { types: [published] }` and `workflow_dispatch` with inputs `tag` and `health_timeout` (30–600, default 120); permissions `id-token: write`, `contents: read`
    - Steps: resolve tag → gate on Docker Hub image availability (fail naming tag if absent, no OIDC/SSM) → OIDC auth via `aws-actions/configure-aws-credentials` with `role-to-assume` and no static-key fallback → SSM reachability check (`describe-instance-information`) → `aws ssm send-command` AWS-RunShellScript (workingDirectory the volume-backed spinsci dir; export `TARGET_VERSION` + `SPINSCI_UPDATE_YES=1`; run `update_remote.sh` then `remote_up.sh`) → capture `CommandId` + `get-command-invocation` output to the step summary → poll `/api/v1/health` → report success/failure naming the tag; no auto-rollback
    - Use no `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` anywhere
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.1, 5.2, 5.3, 8.1, 8.2, 8.3, 9.1, 9.4, 9.5, 9.6, 9.7_

  - [ ]* 11.2 Write a static-analysis test over the workflow YAML
    - Assert the workflow uses `aws ssm send-command` (not ssh), uses `configure-aws-credentials` with `role-to-assume`, references no static AWS key secret, success/failure summaries name the tag, and the failure path issues no second/rollback command
    - _Requirements: 4.3, 5.1, 5.2, 9.5, 9.6, 9.7_

- [ ] 12. Checkpoint - Deploy pipeline logic and workflow
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 13. Author the operator runbook and validate synthesis
  - [x] 13.1 Write `infrastructure/README.md` runbook
    - Document deploy (context inputs + `cdk deploy`), the DLM daily snapshot policy, on-demand `create-snapshot`, and restore (create-volume from snapshot in the AZ, detach/attach at the device, remount)
    - Document the rollback path (`workflow_dispatch` with an older tag) and note deploys perform no auto-rollback
    - _Requirements: 6.5_

  - [x] 13.2 Run `cdk synth` as a dry-run validation over the composed stack
    - Confirm the stack synthesizes with valid inputs and that all template-level properties hold; document (do not execute) the deploy/rollback runbook path
    - _Requirements: 1.8, 1.9_

- [ ] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references specific requirement sub-clauses for traceability and, where applicable, the Correctness Property it should be validated by (property-based test, PBT-eligible).
- Properties 1–6 are CDK synth invariants (driven through real `cdk synth` with `aws-cdk-lib/assertions` + fast-check). Properties 7, 8, 11, 12, 13, 14 are deploy-logic invariants over the extracted pure functions.
- Properties 9 and 10's container-level `.env`/data preservation (Req 6.3, 7.1, 7.3, 7.5, 8.4, 8.5) is integration/manual, not a unit property. Property 10's *bootstrap-decision* half is covered as a unit property in task 6.3; the on-host preservation stays in the integration suite.
- No tasks provision a real AWS account, purchase domains, or require manual sign-off — everything is code/tests/config authored in the repo, ending with a `cdk synth` dry-run and a documented runbook.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["3.1", "4.1", "5.1", "6.1", "10.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "4.2", "4.3", "4.4", "5.2", "6.2", "6.3", "6.4", "7.1", "10.2", "10.3", "10.4", "10.5", "10.6"] },
    { "id": 3, "tasks": ["5.3", "5.4", "7.2", "8.1", "11.1"] },
    { "id": 4, "tasks": ["8.2", "11.2", "13.1"] },
    { "id": 5, "tasks": ["8.3", "13.2"] }
  ]
}
```
