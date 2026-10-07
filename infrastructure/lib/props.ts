import * as cdk from 'aws-cdk-lib';

/**
 * Typed input contract for the SpinSci EC2 CDK stack.
 *
 * This module intentionally contains ONLY types, small pure type-guards, and
 * constants. It does NOT construct any CDK resources, implement the stack, or
 * run validation flow — those live in later tasks (the stack composition in
 * task 8.1 and the entrypoint validation in task 8.2). The constants and guards
 * here exist so the entrypoint validation and the property tests can reuse a
 * single source of truth rather than duplicating literals.
 */

/**
 * Certificate strategy forwarded to `setup_remote.sh` via `CERT_MODE`.
 * (Req 3.4)
 */
export type CertMode = 'auto' | 'sslip' | 'self-signed';

/**
 * Deploy strategy forwarded to `setup_remote.sh` via `DEPLOY_MODE`.
 * (Req 3.4)
 */
export type DeployMode = 'prebuilt' | 'build';

/**
 * Runtime-usable list of valid {@link CertMode} values. Kept in sync with the
 * `CertMode` union above. Used by entrypoint validation (task 8.2) and the
 * property tests so the enum is defined once.
 * (Req 3.4)
 */
export const CERT_MODES = ['auto', 'sslip', 'self-signed'] as const;

/**
 * Runtime-usable list of valid {@link DeployMode} values. Kept in sync with the
 * `DeployMode` union above.
 * (Req 3.4)
 */
export const DEPLOY_MODES = ['prebuilt', 'build'] as const;

/**
 * Inclusive lower bound for the Data_Volume size in GiB. (Req 1.6)
 */
export const DATA_VOLUME_MIN_GIB = 1;

/**
 * Inclusive upper bound for the Data_Volume size in GiB. (Req 1.6)
 */
export const DATA_VOLUME_MAX_GIB = 16384;

/**
 * Type guard narrowing an arbitrary value to {@link CertMode}. Pure; performs no
 * side effects. Reused by entrypoint validation and property tests. (Req 3.4)
 */
export function isCertMode(value: unknown): value is CertMode {
  return (
    typeof value === 'string' &&
    (CERT_MODES as readonly string[]).includes(value)
  );
}

/**
 * Type guard narrowing an arbitrary value to {@link DeployMode}. Pure; performs
 * no side effects. Reused by entrypoint validation and property tests. (Req 3.4)
 */
export function isDeployMode(value: unknown): value is DeployMode {
  return (
    typeof value === 'string' &&
    (DEPLOY_MODES as readonly string[]).includes(value)
  );
}

/**
 * Typed Operator input contract for the SpinSci single-instance EC2 stack.
 *
 * Each field maps to one or more acceptance criteria; see inline references.
 * Defaults for optional-at-the-CLI inputs (`instanceType`, `dataVolumeSizeGiB`,
 * `certMode`, `deployMode`) are applied at the entrypoint (task 8.2) from
 * `cdk.json` context, so by the time props reach the stack they are concrete.
 */
export interface SpinSciEc2StackProps extends cdk.StackProps {
  /**
   * Public domain or host for the deployment. Required — no default is defined,
   * so the entrypoint halts synthesis if it is missing. (Req 1.8)
   */
  readonly host: string;

  /**
   * EC2 instance type (e.g. "t3.large"). Typed as a plain string; the default
   * (`t3.large`) is supplied at the entrypoint from context. (Req 1.3, 1.4)
   */
  readonly instanceType: string;

  /**
   * Data_Volume size in GiB. Must fall within the inclusive bounds
   * [{@link DATA_VOLUME_MIN_GIB}, {@link DATA_VOLUME_MAX_GIB}] =
   * [1, 16384]. The bound is enforced by entrypoint validation (task 8.2);
   * this field only documents it. (Req 1.6)
   */
  readonly dataVolumeSizeGiB: number;

  /**
   * Existing VPC id to import. When set, the stack imports that VPC and places
   * the instance in an existing public subnet; when omitted, the stack creates
   * a new VPC. (Req 1.1, 1.2)
   */
  readonly vpcId?: string;

  /**
   * Allocation id of an existing Elastic IP to associate with the instance
   * (e.g. `eipalloc-053f7e87eb3322f98`). When set, the stack associates this
   * allocation and creates NO new EIP; when omitted, it allocates a fresh one.
   * Supply {@link eipPublicIp} alongside so the setup script receives the real
   * address. (Req 1.5)
   */
  readonly eipAllocationId?: string;

  /**
   * The literal public IPv4 address of {@link eipAllocationId} (e.g.
   * `3.18.59.28`). Required when `eipAllocationId` is set so UserData can
   * forward the real address as `SERVER_IP` (an allocation id is not an IP).
   */
  readonly eipPublicIp?: string;

  /**
   * Certificate mode forwarded to the setup script. (Req 3.4)
   */
  readonly certMode: CertMode;

  /**
   * Deploy mode forwarded to the setup script. (Req 3.4)
   */
  readonly deployMode: DeployMode;

  /**
   * Optional Let's Encrypt contact email forwarded to the setup script.
   */
  readonly letsEncryptEmail?: string;

  /**
   * GitHub repository in "owner/name" form, used to scope the OIDC_Role trust
   * policy to this repository only. (Req 5.5)
   */
  readonly githubRepo: string;

  /**
   * Whether to provision the GitHub OIDC provider and the OIDC deploy role used
   * by the CI/CD Deploy_Pipeline. Defaults to `true`.
   *
   * Set to `false` for a first local deploy where CI/CD is deferred and the
   * deploying principal lacks `iam:CreateOpenIDConnectProvider` (e.g. a scoped
   * SSO role in a shared account). With it off, the stack creates no OIDC
   * provider and no deploy role, so the deploy needs no IAM-provider
   * permissions. Flip it back on (and supply `oidcProviderArn` if a provider
   * already exists in the account) once GitHub CI/CD is ready. (Req 5 — deferred)
   */
  readonly enableDeployRole?: boolean;

  /**
   * ARN of an existing GitHub OIDC provider to import. When omitted, the stack
   * creates the provider; when set, it imports the existing one to avoid a
   * duplicate-provider error. Only consulted when {@link enableDeployRole} is
   * true.
   */
  readonly oidcProviderArn?: string;

  /**
   * Complete ARN of an existing AWS Secrets Manager secret holding the app's
   * EXTERNAL third-party credentials (Cartesia, Groq, Deepgram, OpenAI,
   * Langfuse, PostHog, Sentry, ...) as a flat JSON key→value map.
   *
   * The operator creates and populates this secret out-of-band; the stack only
   * IMPORTS it by ARN and grants the instance role least-privilege read. Secret
   * material is therefore never stored in CDK/CloudFormation. When omitted, no
   * Secrets Manager permission is attached and the runtime fetch is inert — the
   * app falls back to whatever is in `.env` (Req: secrets handling).
   *
   * Must be the COMPLETE ARN (with the trailing 6-char suffix), e.g.
   * `arn:aws:secretsmanager:us-east-2:032398581868:secret:spinsci/prod/app-AbCdEf`.
   * The box-internal secrets (DB/Redis/MinIO/TURN/JWT) stay generated locally
   * by `setup_remote.sh` and never go here.
   */
  readonly appSecretArn?: string;

  /**
   * Optional ARN of the customer-managed KMS key that encrypts
   * {@link appSecretArn}. Supply this only when the secret is encrypted with a
   * CMK (not the AWS-managed `aws/secretsmanager` key); the stack then also
   * grants the instance role `kms:Decrypt` on exactly this key. With the
   * AWS-managed key, Secrets Manager handles decryption implicitly and no KMS
   * grant is needed.
   */
  readonly kmsKeyArn?: string;

  /**
   * Name of an existing S3 bucket the app uses for object storage (call audio,
   * transcripts) when it runs with `ENABLE_AWS_S3=true` instead of the bundled
   * MinIO container. When set, the stack grants the instance role
   * least-privilege, bucket-scoped read/write (`s3:GetObject`, `s3:PutObject`,
   * `s3:DeleteObject`, `s3:AbortMultipartUpload` on the objects, plus
   * `s3:ListBucket` / `s3:GetBucketLocation` on the bucket) so the box can use
   * the bucket via its instance role with no static AWS keys in `.env`.
   *
   * The bucket itself is created and hardened out-of-band (private, encrypted,
   * public access blocked); the stack only IMPORTS it by name and attaches the
   * grant. When omitted, no S3 permission is attached and the box keeps using
   * MinIO (`ENABLE_AWS_S3=false`). (MinIO → S3 migration)
   */
  readonly audioBucketName?: string;
}
