# Requirements Document

## Introduction

This feature provisions and deploys the SpinSci voice AI application onto a single AWS EC2 instance using AWS CDK (TypeScript) for infrastructure-as-code, and adds an automated release-to-deploy pipeline driven by GitHub Actions using AWS Systems Manager (SSM) Run Command.

The feature deliberately **reuses** the existing, working build and runtime tooling and fills only the gaps around them:

- The multi-arch Docker build/push pipeline (`.github/workflows/docker-image.yml`) already builds `spinsci-api` and `spinsci-ui` and pushes version-tagged images to Docker Hub and GHCR on GitHub release. It is reused as-is.
- The `docker-compose.yaml` remote runtime stack (Postgres+pgvector, Redis, MinIO, api, ui, nginx, coturn, optional cloudflared) is reused as-is. Data services run as containers on the box with Docker volumes.
- The provisioning script `scripts/setup_remote.sh` (root/cloud-init entrypoint that installs Docker, generates `.env` secrets, issues certificates, validates config, and starts via `remote_up.sh`) is reused as-is.
- The upgrade script `scripts/update_remote.sh` (prebuilt-image install/upgrade path that refreshes deployment files, pins image tags, revalidates, and restarts via `remote_up.sh`) is reused as-is.

The scope of this feature is therefore two gaps: (1) the CDK stack that provisions the EC2 host and its supporting AWS resources and bootstraps it by invoking the existing scripts, and (2) the GitHub Actions job that, after images are published, drives a remote deploy through SSM Run Command. Application logic, multi-tenancy, and the Docker build/compose runtime are explicitly out of scope.

## Glossary

- **CDK_Stack**: The AWS CDK application (TypeScript) that defines and provisions all AWS infrastructure for a single-instance SpinSci deployment.
- **EC2_Instance**: The single Amazon EC2 virtual machine that runs the SpinSci `docker-compose.yaml` stack.
- **Data_Volume**: The Amazon EBS volume attached to the EC2_Instance that holds the Docker data directory (Postgres, Redis, and MinIO container volumes).
- **Instance_Profile**: The IAM role and instance profile attached to the EC2_Instance, granting it AWS permissions including AWS Systems Manager (SSM) managed-instance capability.
- **UserData_Script**: The CDK-provided EC2 user-data (cloud-init) script that runs once as root on first boot to install prerequisites and invoke `scripts/setup_remote.sh`.
- **Setup_Script**: The existing `scripts/setup_remote.sh` provisioning script.
- **Update_Script**: The existing `scripts/update_remote.sh` prebuilt-install upgrade script.
- **Build_Pipeline**: The existing `.github/workflows/docker-image.yml` GitHub Actions workflow that builds and publishes tagged container images on GitHub release.
- **Deploy_Pipeline**: The new GitHub Actions job that deploys a released version to the EC2_Instance via SSM Run Command after the Build_Pipeline publishes images.
- **SSM_Command**: An AWS Systems Manager Run Command invocation that executes a shell command on the EC2_Instance without inbound SSH.
- **OIDC_Role**: The AWS IAM role that GitHub Actions assumes via OpenID Connect federation, using short-lived credentials instead of long-lived AWS access keys.
- **Elastic_IP**: The static AWS Elastic IP address associated with the EC2_Instance.
- **Security_Group**: The AWS security group controlling network ingress and egress for the EC2_Instance.
- **Release_Tag**: The Git tag of a published GitHub release (for example `spinsci-v1.28.0`), used to derive the container image tag deployed to the EC2_Instance.
- **Operator**: The human who configures and runs the CDK_Stack deployment.
- **Health_Endpoint**: The application health check served at `/api/v1/health`.

## Requirements

### Requirement 1: Provision core AWS infrastructure via CDK

**User Story:** As an Operator, I want the CDK_Stack to provision the AWS resources for a single-instance SpinSci deployment, so that I can stand up the host without manually creating AWS resources.

#### Acceptance Criteria

1. THE CDK_Stack SHALL provision networking resources consisting of a VPC and at least one public subnet in which the EC2_Instance receives a public IP address.
2. WHERE the Operator supplies an existing VPC identifier, THE CDK_Stack SHALL provision the EC2_Instance into the supplied VPC instead of creating a new VPC.
3. WHEN the Operator supplies an EC2 instance type, THE CDK_Stack SHALL provision exactly one EC2_Instance of that instance type.
4. WHEN the Operator omits the EC2 instance type, THE CDK_Stack SHALL provision exactly one EC2_Instance using a documented default instance type.
5. THE CDK_Stack SHALL provision exactly one Elastic_IP and associate it with the EC2_Instance such that the associated address is reported as the EC2_Instance public IP address.
6. THE CDK_Stack SHALL provision exactly one Data_Volume as an EBS volume, using an Operator-configurable size between 1 GiB and 16384 GiB with a documented default, and attach the Data_Volume to the EC2_Instance.
7. THE CDK_Stack SHALL provision an Instance_Profile that grants the EC2_Instance AWS Systems Manager managed-instance permissions.
8. THE CDK_Stack SHALL accept AWS region, EC2 instance type, and public domain or host as Operator-configurable inputs.
9. IF the Operator does not supply a required input for which no default is defined, THEN THE CDK_Stack SHALL halt provisioning and return an error indicating which required input is missing, without creating AWS resources.

### Requirement 2: Enforce least-privilege network ingress

**User Story:** As an Operator, I want the Security_Group to expose only the ports the SpinSci stack requires and to exclude SSH, so that the attack surface stays minimal.

#### Acceptance Criteria

1. THE Security_Group SHALL allow inbound TCP traffic on port 80 from any IPv4 source (`0.0.0.0/0`).
2. THE Security_Group SHALL allow inbound TCP traffic on port 443 from any IPv4 source (`0.0.0.0/0`).
3. THE Security_Group SHALL allow inbound TCP and UDP traffic on ports 3478 and 5349 from any IPv4 source (`0.0.0.0/0`).
4. THE Security_Group SHALL allow inbound UDP traffic on ports 49152 through 49200 inclusive from any IPv4 source (`0.0.0.0/0`).
5. THE Security_Group SHALL exclude any inbound rule permitting TCP or UDP traffic on port 22.
6. THE CDK_Stack SHALL rely on AWS Systems Manager Session Manager for administrative shell access to the EC2_Instance and SHALL NOT provision an inbound SSH ingress rule for administrative access.

### Requirement 3: Bootstrap the instance through the existing setup script

**User Story:** As an Operator, I want the CDK UserData_Script to install prerequisites and hand off provisioning to the existing Setup_Script, so that CDK does not duplicate the provisioning logic that already lives in the scripts.

#### Acceptance Criteria

1. WHEN the EC2_Instance boots for the first time, THE UserData_Script SHALL install the prerequisites required to run the Setup_Script and then invoke the Setup_Script.
2. THE UserData_Script SHALL invoke the Setup_Script as root without an interactive terminal.
3. THE UserData_Script SHALL provide the EC2_Instance public IP address to the Setup_Script through the `SERVER_IP` environment variable.
4. THE UserData_Script SHALL pass deployment mode and certificate mode to the Setup_Script through the `DEPLOY_MODE` and `CERT_MODE` environment variables when the Operator supplies them.
5. THE CDK_Stack SHALL contain no reimplementation of the Docker installation, secret generation, certificate issuance, or stack-start logic already provided by the Setup_Script.
6. THE UserData_Script SHALL configure the SpinSci Docker data directory to reside on the mounted Data_Volume.

### Requirement 4: Deploy a released version via SSM Run Command

**User Story:** As an Operator, I want each published GitHub release to deploy automatically to the EC2_Instance through SSM Run Command, so that a release reaches the running host without manual SSH steps.

#### Acceptance Criteria

1. WHEN a GitHub release is published, IF the Build_Pipeline has published the container images for the Release_Tag, THEN THE Deploy_Pipeline SHALL issue an SSM_Command that runs the Update_Script on the EC2_Instance.
2. THE Deploy_Pipeline SHALL pass the Release_Tag to the Update_Script through the `TARGET_VERSION` environment variable so that the deployed images are pinned to the released version.
3. THE Deploy_Pipeline SHALL run the SSM_Command without opening any inbound SSH connection to the EC2_Instance.
4. WHEN the Deploy_Pipeline issues the SSM_Command, THE Deploy_Pipeline SHALL record the SSM_Command identifier and the command output so that the execution is auditable.
5. IF the Build_Pipeline has not published the images for the Release_Tag, THEN THE Deploy_Pipeline SHALL NOT issue the SSM_Command and SHALL report a failure status that identifies the Release_Tag.
6. IF issuing the SSM_Command fails, THEN THE Deploy_Pipeline SHALL mark the deploy as failed and record the error.
7. IF the EC2_Instance is not reachable as an SSM managed instance, THEN THE Deploy_Pipeline SHALL mark the deploy as failed and record the error.

### Requirement 5: Authenticate GitHub Actions to AWS via OIDC

**User Story:** As an Operator, I want the Deploy_Pipeline to authenticate to AWS using short-lived OIDC credentials, so that no long-lived AWS keys are stored in GitHub.

#### Acceptance Criteria

1. WHEN the Deploy_Pipeline begins a deploy, THE Deploy_Pipeline SHALL obtain temporary AWS credentials by assuming the OIDC_Role through GitHub OpenID Connect federation.
2. THE Deploy_Pipeline SHALL exclude any static AWS access key or secret access key stored as a GitHub secret.
3. IF assuming the OIDC_Role fails, THEN THE Deploy_Pipeline SHALL mark the deploy as failed, SHALL NOT issue the SSM_Command, and SHALL NOT fall back to any static AWS access key or secret access key.
4. THE OIDC_Role SHALL grant only the permissions required to issue an SSM_Command against the EC2_Instance and read the resulting SSM_Command output, and SHALL exclude permissions beyond issuing that SSM_Command and reading its result.
5. THE CDK_Stack SHALL provision the OIDC_Role with a trust policy that permits role assumption only from the SpinSci repository and rejects role assumption requests originating from any other repository.

### Requirement 6: Preserve persistent data across updates

**User Story:** As an Operator, I want application data to survive instance replacement and stack updates, so that a redeploy does not lose Postgres, Redis, or object-storage data.

#### Acceptance Criteria

1. WHEN the CDK_Stack is updated, THE CDK_Stack SHALL preserve the existing Data_Volume and its stored data without deleting, detaching, or recreating the Data_Volume.
2. WHILE the SpinSci stack is running, THE EC2_Instance SHALL store the Postgres, Redis, and MinIO Docker container volumes on the mounted Data_Volume.
3. WHEN the Deploy_Pipeline deploys a new version, THE EC2_Instance SHALL retain the existing Data_Volume contents unchanged for the Postgres, Redis, and MinIO volumes.
4. WHEN the CDK_Stack replaces the EC2_Instance, THE CDK_Stack SHALL retain the existing Data_Volume and attach it to the replacement EC2_Instance so that the Postgres, Redis, and MinIO data stored before replacement remains available after replacement.
5. THE requirements documentation SHALL describe a backup approach for the Postgres and MinIO data stored on the Data_Volume that identifies EBS snapshots as the backup mechanism and states how a snapshot is created and how the Data_Volume is restored from a snapshot.

### Requirement 7: Preserve generated secrets across redeploys

**User Story:** As an Operator, I want the application secrets generated on first boot to persist across redeploys, so that sessions, database access, and TURN authentication keep working after an update.

#### Acceptance Criteria

1. WHEN the EC2_Instance boots for the first time and no `.env` file exists, THE Setup_Script SHALL generate the `OSS_JWT_SECRET`, database password, Redis password, MinIO credentials, and TURN secret into the `.env` file.
2. WHEN the Setup_Script creates the `.env` file, THE EC2_Instance SHALL store the `.env` file on the Data_Volume so that it persists across instance replacement and stack updates.
3. WHEN the Deploy_Pipeline deploys a new version, THE EC2_Instance SHALL reuse the existing `.env` secrets without regenerating the `OSS_JWT_SECRET`, database password, Redis password, MinIO credentials, or TURN secret.
4. IF an existing `.env` file is present on the EC2_Instance, THEN THE UserData_Script SHALL NOT re-run the first-boot secret generation path of the Setup_Script, and THE existing `.env` file SHALL remain unchanged.
5. WHEN a redeploy completes, THE EC2_Instance SHALL retain the same value for each of the `OSS_JWT_SECRET`, database password, Redis password, MinIO credentials, and TURN secret that was present in the `.env` file before the redeploy.

### Requirement 8: Roll back to a previous released version

**User Story:** As an Operator, I want to redeploy a previously released version through the same SSM path, so that I can recover from a bad release.

#### Acceptance Criteria

1. WHEN the Operator manually triggers the Deploy_Pipeline with a selected Release_Tag, THE Deploy_Pipeline SHALL issue one SSM_Command that runs the Update_Script on the EC2_Instance with the `TARGET_VERSION` environment variable set to the selected Release_Tag.
2. WHEN the Operator selects a Release_Tag whose publication date precedes the most recently published release, THE Deploy_Pipeline SHALL issue the SSM_Command for that Release_Tag without rejecting or substituting it based on its being older than the latest release.
3. IF the Build_Pipeline has not published the container images for the selected Release_Tag, THEN THE Deploy_Pipeline SHALL NOT issue the SSM_Command and SHALL report a failure status that identifies the selected Release_Tag.
4. WHEN a rollback deploy runs, THE EC2_Instance SHALL retain the existing Data_Volume contents unchanged.
5. WHEN a rollback deploy runs, THE EC2_Instance SHALL reuse the existing `.env` secrets without regenerating the `OSS_JWT_SECRET`, database password, Redis password, MinIO credentials, or TURN secret.

### Requirement 9: Verify and surface deploy outcome

**User Story:** As an Operator, I want the deploy to verify application health and report success or failure, so that I know whether a release is live.

#### Acceptance Criteria

1. WHEN the Update_Script completes on the EC2_Instance, THE Deploy_Pipeline SHALL poll the Health_Endpoint at `/api/v1/health` at a fixed interval between 5 and 30 seconds until the endpoint reports healthy or the timeout elapses.
2. THE Deploy_Pipeline SHALL treat the Health_Endpoint as healthy only when it returns a successful response indicating the application is healthy, and SHALL treat an unreachable, timed-out, or error response as not healthy.
3. THE Deploy_Pipeline SHALL use an Operator-configurable health-check timeout between 30 and 600 seconds, defaulting to 120 seconds when the Operator supplies no value.
4. IF the Health_Endpoint does not report healthy within the configured timeout, THEN THE Deploy_Pipeline SHALL mark the deploy as failed.
5. WHEN a deploy fails, THE EC2_Instance SHALL preserve its running state and THE Deploy_Pipeline SHALL NOT perform an automatic rollback.
6. WHEN the deploy succeeds, THE Deploy_Pipeline SHALL report a success status that identifies the Release_Tag.
7. WHEN the deploy fails, THE Deploy_Pipeline SHALL report a failure status that identifies the Release_Tag and indicates that health verification did not succeed.

## Assumptions and Non-Goals

- **Reuse over reimplementation:** The Docker build/push Build_Pipeline (`.github/workflows/docker-image.yml`) and the `docker-compose.yaml` runtime stack already exist and are reused unchanged. This spec adds only the CDK_Stack and the Deploy_Pipeline. The bootstrap and deploy logic remains in `scripts/setup_remote.sh`, `scripts/update_remote.sh`, and `remote_up.sh`; the CDK_Stack invokes those scripts and does not fork their logic.
- **Deployment topology:** The target is a single EC2 instance running the self-contained compose stack with data services as containers. ECS/Fargate and EKS are explicitly out of scope.
- **Helm coexistence:** A `deploy/helm/spinsci` chart exists as a possible future EKS path. Reconciling the EC2 target with the Helm chart is a non-goal; the two are assumed to coexist, and this spec addresses only the EC2 target.
- **Application concerns out of scope:** Strict multi-tenancy, application feature behavior, and other app-level concerns are out of scope. This spec covers infrastructure provisioning and deploy automation only.
- **Deploy scripts are bash-only:** New deployment and CI scripts introduced by this feature are bash-only and do not require PowerShell counterparts, consistent with the existing deployment/CI scripts.
