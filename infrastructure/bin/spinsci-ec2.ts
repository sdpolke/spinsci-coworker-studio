#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';

import {
  CERT_MODES,
  DATA_VOLUME_MAX_GIB,
  DATA_VOLUME_MIN_GIB,
  DEPLOY_MODES,
  SpinSciEc2StackProps,
  isCertMode,
  isDeployMode,
} from '../lib/props';
import { SpinSciEc2Stack } from '../lib/spinsci-ec2-stack';

/**
 * CDK app entrypoint for the SpinSci single-instance EC2 deployment.
 *
 * This file reads Operator inputs from CDK context (cdk.json defaults,
 * `-c key=value`, or `--context`) and validates the ones that have NO default
 * (`region`, `host`) BEFORE instantiating the stack. On a missing or invalid
 * required input it throws an Error whose message names the input and exits
 * non-zero, so `cdk synth`/`cdk deploy` aborts and no resources are created
 * (Req 1.8, 1.9 / Property 6).
 *
 * Inputs with documented defaults (`instanceType`, `dataVolumeSizeGiB`,
 * `certMode`, `deployMode`, `githubRepo`) are read from context (where cdk.json
 * supplies the defaults) and range/enum-validated here so the props reaching
 * the stack are already concrete and valid.
 */

/** Read a string context value, returning undefined when unset/blank. */
function ctxString(app: cdk.App, key: string): string | undefined {
  const value = app.node.tryGetContext(key);
  if (value === undefined || value === null) return undefined;
  const s = String(value).trim();
  return s.length === 0 ? undefined : s;
}

/**
 * Resolve, validate, and assemble the stack props from context + env.
 * Throws a descriptive Error (naming the offending input) on any invalid or
 * missing-required input. Pure except for reading app context, so the entry
 * logic is unit-testable (task 8.3).
 */
export function resolveStackProps(app: cdk.App): {
  env: cdk.Environment;
  props: SpinSciEc2StackProps;
} {
  // --- Required inputs (no default): region + host (Req 1.8, 1.9) -----------
  // Region may come from the `region` context key or the standard CDK env var.
  const region =
    ctxString(app, 'region') ??
    process.env.CDK_DEFAULT_REGION ??
    process.env.AWS_REGION;
  if (!region) {
    throw new Error(
      'Missing required input "region": set it via `-c region=<aws-region>` ' +
        '(e.g. us-east-2) or the CDK_DEFAULT_REGION environment variable. ' +
        'No resources were synthesized.',
    );
  }

  const host = ctxString(app, 'host');
  if (!host) {
    throw new Error(
      'Missing required input "host": set the public domain or host via ' +
        '`-c host=<domain-or-ip>`. No resources were synthesized.',
    );
  }

  const account =
    ctxString(app, 'account') ?? process.env.CDK_DEFAULT_ACCOUNT;

  // --- Defaulted inputs: validate range/enum (Req 1.3, 1.6, 3.4) ------------
  const instanceType = ctxString(app, 'instanceType') ?? 't3.large';

  const rawSize = app.node.tryGetContext('dataVolumeSizeGiB');
  const dataVolumeSizeGiB = rawSize === undefined ? 100 : Number(rawSize);
  if (
    !Number.isInteger(dataVolumeSizeGiB) ||
    dataVolumeSizeGiB < DATA_VOLUME_MIN_GIB ||
    dataVolumeSizeGiB > DATA_VOLUME_MAX_GIB
  ) {
    throw new Error(
      `Invalid input "dataVolumeSizeGiB": must be an integer within ` +
        `[${DATA_VOLUME_MIN_GIB}, ${DATA_VOLUME_MAX_GIB}] GiB, got ` +
        `${String(rawSize)}. No resources were synthesized.`,
    );
  }

  const certMode = ctxString(app, 'certMode') ?? 'auto';
  if (!isCertMode(certMode)) {
    throw new Error(
      `Invalid input "certMode": must be one of ${CERT_MODES.join(', ')}, ` +
        `got "${certMode}". No resources were synthesized.`,
    );
  }

  const deployMode = ctxString(app, 'deployMode') ?? 'prebuilt';
  if (!isDeployMode(deployMode)) {
    throw new Error(
      `Invalid input "deployMode": must be one of ${DEPLOY_MODES.join(', ')}, ` +
        `got "${deployMode}". No resources were synthesized.`,
    );
  }

  const githubRepo = ctxString(app, 'githubRepo');
  if (!githubRepo) {
    throw new Error(
      'Missing required input "githubRepo": set the "owner/name" slug via ' +
        '`-c githubRepo=<owner/name>` (needed to scope the OIDC trust policy). ' +
        'No resources were synthesized.',
    );
  }

  const vpcId = ctxString(app, 'vpcId');

  // Optional existing Elastic IP to reuse (association only, no new allocation).
  // Require both the allocation id and its literal address together.
  const eipAllocationId = ctxString(app, 'eipAllocationId');
  const eipPublicIp = ctxString(app, 'eipPublicIp');
  if (eipAllocationId && !/^eipalloc-[0-9a-f]+$/.test(eipAllocationId)) {
    throw new Error(
      `Invalid input "eipAllocationId": expected an eipalloc-… id, got ` +
        `"${eipAllocationId}". No resources were synthesized.`,
    );
  }
  if (eipPublicIp && !/^\d{1,3}(\.\d{1,3}){3}$/.test(eipPublicIp)) {
    throw new Error(
      `Invalid input "eipPublicIp": expected an IPv4 address, got ` +
        `"${eipPublicIp}". No resources were synthesized.`,
    );
  }
  if (Boolean(eipAllocationId) !== Boolean(eipPublicIp)) {
    throw new Error(
      'Inputs "eipAllocationId" and "eipPublicIp" must be supplied together: ' +
        'the allocation id associates the address and the IP is forwarded as ' +
        'SERVER_IP. No resources were synthesized.',
    );
  }

  const letsEncryptEmail = ctxString(app, 'letsEncryptEmail');
  const oidcProviderArn = ctxString(app, 'oidcProviderArn');

  // CI/CD deploy role toggle. Defaults to true; accept false via `-c
  // enableDeployRole=false` (context values are strings) to skip the OIDC
  // provider + deploy role for a first local deploy.
  const enableDeployRoleCtx = app.node.tryGetContext('enableDeployRole');
  const enableDeployRole = !(
    enableDeployRoleCtx === false || String(enableDeployRoleCtx) === 'false'
  );

  // Optional app-secret integration (Secrets Manager). Validate ARN shapes so a
  // typo fails fast at synth rather than at deploy time. Both are optional; when
  // appSecretArn is unset the secret fetch is inert.
  const appSecretArn = ctxString(app, 'appSecretArn');
  if (appSecretArn && !isSecretsManagerArn(appSecretArn)) {
    throw new Error(
      `Invalid input "appSecretArn": must be a complete Secrets Manager secret ` +
        `ARN (arn:aws:secretsmanager:<region>:<account>:secret:<name>-<suffix>), ` +
        `got "${appSecretArn}". No resources were synthesized.`,
    );
  }

  const kmsKeyArn = ctxString(app, 'kmsKeyArn');
  if (kmsKeyArn && !isKmsKeyArn(kmsKeyArn)) {
    throw new Error(
      `Invalid input "kmsKeyArn": must be a KMS key ARN ` +
        `(arn:aws:kms:<region>:<account>:key/<id>), got "${kmsKeyArn}". ` +
        'No resources were synthesized.',
    );
  }
  if (kmsKeyArn && !appSecretArn) {
    throw new Error(
      'Input "kmsKeyArn" was supplied without "appSecretArn": the KMS grant ' +
        'only makes sense alongside an imported app secret. No resources were ' +
        'synthesized.',
    );
  }

  // Optional S3 object-storage bucket (ENABLE_AWS_S3=true path). Imported by
  // name; validate against S3 bucket naming rules so a typo fails at synth.
  const audioBucketName = ctxString(app, 'audioBucketName');
  if (audioBucketName && !isS3BucketName(audioBucketName)) {
    throw new Error(
      `Invalid input "audioBucketName": must be a valid S3 bucket name ` +
        `(3-63 chars, lowercase letters, digits, dots and hyphens; start and ` +
        `end alphanumeric), got "${audioBucketName}". No resources were ` +
        'synthesized.',
    );
  }

  const env: cdk.Environment = { account, region };

  const props: SpinSciEc2StackProps = {
    env,
    host,
    instanceType,
    dataVolumeSizeGiB,
    vpcId,
    eipAllocationId,
    eipPublicIp,
    certMode,
    deployMode,
    letsEncryptEmail,
    githubRepo,
    enableDeployRole,
    oidcProviderArn,
    appSecretArn,
    kmsKeyArn,
    audioBucketName,
  };

  return { env, props };
}

/**
 * Validate a COMPLETE Secrets Manager secret ARN (including the trailing
 * 6-char suffix Secrets Manager appends). Importing by complete ARN lets the
 * IAM grant be scoped to exactly this secret.
 */
function isSecretsManagerArn(arn: string): boolean {
  return /^arn:aws[a-z-]*:secretsmanager:[a-z0-9-]+:\d{12}:secret:.+-[A-Za-z0-9]{6}$/.test(
    arn,
  );
}

/** Validate a KMS key ARN (key/<uuid>, not an alias). */
function isKmsKeyArn(arn: string): boolean {
  return /^arn:aws[a-z-]*:kms:[a-z0-9-]+:\d{12}:key\/[A-Za-z0-9-]+$/.test(arn);
}

/**
 * Validate an S3 bucket name against the common DNS-compatible rules the app's
 * buckets follow: 3-63 chars, lowercase letters/digits/dots/hyphens, starting
 * and ending with an alphanumeric. (Not IP-formatted — rejected implicitly by
 * requiring at least one non-digit segment is overkill here; a typo in a
 * hand-set name is what this guards against.)
 */
function isS3BucketName(name: string): boolean {
  return /^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(name);
}

const app = new cdk.App();
const { props } = resolveStackProps(app);

new SpinSciEc2Stack(app, 'SpinSciEc2Stack', props);

app.synth();
