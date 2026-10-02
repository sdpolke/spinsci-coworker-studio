import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

import { SpinSciEc2StackProps } from './props';

/**
 * GitHub Actions OIDC issuer URL. The OIDC provider is created for this issuer
 * (or an existing one is imported by ARN) so the Deploy_Pipeline can assume the
 * OIDC_Role via web identity federation. (Req 5.1)
 */
const GITHUB_OIDC_ISSUER = 'https://token.actions.githubusercontent.com';

/**
 * The single audience GitHub's OIDC tokens carry when
 * `aws-actions/configure-aws-credentials` requests them. (Req 5.5)
 */
const GITHUB_OIDC_AUDIENCE = 'sts.amazonaws.com';

/**
 * The SSM document the Deploy_Pipeline runs on the instance. `ssm:SendCommand`
 * is resource-scoped to this document ARN plus the instance ARN. (Req 5.4)
 */
const RUN_SHELL_SCRIPT_DOCUMENT = 'AWS-RunShellScript';

/**
 * IAM construct for the SpinSci single-instance EC2 deployment.
 *
 * Responsibilities:
 *  - Provide the Instance_Profile that makes the EC2_Instance an AWS Systems
 *    Manager managed instance (Session Manager + Run Command), with the
 *    least-privilege managed policy and nothing more (Req 1.7). The compute
 *    construct (task 7.1) attaches the exposed instance profile to the
 *    instance.
 *  - (Task 5.2) Provide the GitHub OIDC provider and the OIDC_Role the
 *    Deploy_Pipeline assumes via web identity (Req 5.2, 5.4, 5.5). That portion
 *    is implemented separately; see the marked placeholder below.
 *
 * This construct does NOT create the instance, Elastic IP, EBS volume,
 * networking, or UserData — those live in sibling constructs.
 */

/**
 * Props for {@link IamConstruct}.
 *
 * The full {@link SpinSciEc2StackProps} is accepted (rather than a narrow
 * subset) so that task 5.2 can read `githubRepo` and `oidcProviderArn` from it
 * when it adds the OIDC provider + OIDC_Role, without reshaping this interface.
 */
export interface IamConstructProps {
  /** The typed Operator input contract for the stack. */
  readonly stackProps: SpinSciEc2StackProps;
}

export class IamConstruct extends Construct {
  /**
   * The IAM role assumed by the EC2_Instance (via the EC2 service principal).
   * Carries `AmazonSSMManagedInstanceCore` so the box registers as an SSM
   * managed instance. Exposed so the compute construct can reference it.
   * (Req 1.7)
   */
  public readonly instanceRole: iam.Role;

  /**
   * The Instance_Profile wrapping {@link instanceRole}. The compute construct
   * (task 7.1) attaches this to the EC2_Instance. (Req 1.7)
   */
  public readonly instanceProfile: iam.InstanceProfile;

  /**
   * The GitHub OIDC provider the OIDC_Role trusts. Created for the GitHub
   * issuer, or imported when `oidcProviderArn` is supplied, so re-running
   * against an account that already has the provider does not fail with a
   * duplicate-provider error. (Req 5.1)
   *
   * `undefined` when `enableDeployRole` is false — no OIDC provider is created,
   * so a first local deploy needs no IAM-provider permissions.
   */
  public readonly githubOidcProvider?: iam.IOpenIdConnectProvider;

  /**
   * The role GitHub Actions assumes via web identity. Populated by
   * {@link addDeployRole}, which must be called once the EC2 instance exists so
   * `ssm:SendCommand` can be scoped to that instance's ARN. (Req 5.2, 5.4, 5.5)
   */
  public deployRole?: iam.Role;

  private readonly props: SpinSciEc2StackProps;

  constructor(scope: Construct, id: string, props: IamConstructProps) {
    super(scope, id);

    this.props = props.stackProps;

    this.instanceRole = this.buildInstanceRole();
    this.instanceProfile = new iam.InstanceProfile(this, 'InstanceProfile', {
      role: this.instanceRole,
    });

    // Only touch GitHub OIDC when the CI/CD deploy role is enabled. Skipping it
    // keeps a first local deploy free of iam:CreateOpenIDConnectProvider.
    if (this.props.enableDeployRole !== false) {
      this.githubOidcProvider = this.resolveOidcProvider();
    }
  }

  /**
   * Create the OIDC_Role whose `ssm:SendCommand` grant is scoped to the given
   * instance. Called by the stack after the compute construct creates the
   * instance, since the instance ARN is not known at IAM-construct
   * construction time.
   *
   * The role:
   *  - is assumed only via web identity from the configured GitHub repo
   *    (`:sub` = `repo:<githubRepo>:*`, `:aud` = `sts.amazonaws.com`) so no
   *    other repository can assume it (Req 5.5);
   *  - grants exactly the least-privilege SSM send-and-read actions, with
   *    `ssm:SendCommand` resource-scoped to this instance and the
   *    `AWS-RunShellScript` document (Req 5.4);
   *  - carries no `iam:PassRole`, no wildcard admin, and relies on no static
   *    credentials (Req 5.2).
   *
   * @param instanceId the EC2 instance id the Deploy_Pipeline targets
   * @returns the created OIDC_Role
   */
  public addDeployRole(instanceId: string): iam.Role | undefined {
    // Deferred CI/CD: no OIDC provider was created, so there is nothing to
    // build a web-identity deploy role against. Return undefined; the stack
    // simply omits the DeployRoleArn output.
    if (this.props.enableDeployRole === false || !this.githubOidcProvider) {
      return undefined;
    }

    const stack = cdk.Stack.of(this);
    const { region, account } = stack;

    // Trust: web identity from GitHub's OIDC provider, scoped to this repo.
    // The `:sub` condition rejects tokens from any other repository (Req 5.5).
    const principal = new iam.OpenIdConnectPrincipal(this.githubOidcProvider, {
      StringEquals: {
        [`token.actions.githubusercontent.com:aud`]: GITHUB_OIDC_AUDIENCE,
      },
      StringLike: {
        [`token.actions.githubusercontent.com:sub`]: `repo:${this.props.githubRepo}:*`,
      },
    });

    const role = new iam.Role(this, 'DeployRole', {
      assumedBy: principal,
      description:
        'GitHub Actions OIDC role: issue + read a single SSM RunShellScript ' +
        `command against the SpinSci instance (${this.props.githubRepo})`,
      maxSessionDuration: cdk.Duration.hours(1),
    });

    const instanceArn = `arn:${stack.partition}:ec2:${region}:${account}:instance/${instanceId}`;
    const documentArn = `arn:${stack.partition}:ssm:${region}::document/${RUN_SHELL_SCRIPT_DOCUMENT}`;

    // Send exactly one shell-script command, only to this instance, only using
    // the AWS-RunShellScript document. (Req 5.4)
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SendRunShellScriptToInstance',
        effect: iam.Effect.ALLOW,
        actions: ['ssm:SendCommand'],
        resources: [instanceArn, documentArn],
      }),
    );

    // Read the command result so the deploy is auditable (Req 4.4). These
    // actions do not support resource-level scoping for command invocations,
    // so Resource is '*' but the action set is tightly bounded. (Req 5.4)
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'ReadCommandResults',
        effect: iam.Effect.ALLOW,
        actions: [
          'ssm:GetCommandInvocation',
          'ssm:ListCommandInvocations',
          'ssm:ListCommands',
        ],
        resources: ['*'],
      }),
    );

    // Detect an unreachable managed instance before sending (Req 4.7). Read-only.
    role.addToPolicy(
      new iam.PolicyStatement({
        sid: 'DescribeInstanceReachability',
        effect: iam.Effect.ALLOW,
        actions: ['ssm:DescribeInstanceInformation'],
        resources: ['*'],
      }),
    );

    this.deployRole = role;
    return role;
  }

  /**
   * Grant the EC2 instance role least-privilege read on an existing app secret
   * (imported by complete ARN), so the runtime entrypoint can resolve the
   * external third-party credentials at container start.
   *
   * Security properties:
   *  - the secret is IMPORTED, never created here, so no secret material enters
   *    CDK/CloudFormation;
   *  - `grantRead` attaches `secretsmanager:GetSecretValue` (+ DescribeSecret)
   *    scoped to EXACTLY this secret ARN — no wildcard;
   *  - the grant lands only on the INSTANCE role; the OIDC deploy role is never
   *    given secret access (it only sends SSM commands);
   *  - when the secret is encrypted with a customer-managed KMS key, the
   *    instance role also gets `kms:Decrypt` scoped to that key alone.
   *
   * Called by the stack only when `appSecretArn` is supplied.
   *
   * @param appSecretArn complete Secrets Manager secret ARN
   * @param kmsKeyArn optional CMK ARN encrypting the secret
   */
  public addAppSecretAccess(appSecretArn: string, kmsKeyArn?: string): void {
    const secret = secretsmanager.Secret.fromSecretCompleteArn(
      this,
      'AppSecret',
      appSecretArn,
    );

    // Resource-scoped GetSecretValue + DescribeSecret on this secret only.
    secret.grantRead(this.instanceRole);

    // Only needed for a customer-managed KMS key; the AWS-managed
    // aws/secretsmanager key is decrypted implicitly by the service.
    if (kmsKeyArn) {
      const key = kms.Key.fromKeyArn(this, 'AppSecretKmsKey', kmsKeyArn);
      key.grantDecrypt(this.instanceRole);
    }
  }

  /**
   * Create the GitHub OIDC provider, or import an existing one by ARN when
   * `oidcProviderArn` is supplied (avoids the one-per-account
   * duplicate-provider error). (Req 5.1)
   */
  private resolveOidcProvider(): iam.IOpenIdConnectProvider {
    if (this.props.oidcProviderArn) {
      return iam.OpenIdConnectProvider.fromOpenIdConnectProviderArn(
        this,
        'GithubOidcProvider',
        this.props.oidcProviderArn,
      );
    }

    return new iam.OpenIdConnectProvider(this, 'GithubOidcProvider', {
      url: GITHUB_OIDC_ISSUER,
      clientIds: [GITHUB_OIDC_AUDIENCE],
    });
  }

  /**
   * Build the EC2_Instance role with exactly the SSM managed-instance
   * permissions and nothing else.
   *
   * `AmazonSSMManagedInstanceCore` is the least privilege that makes the box a
   * managed instance for Session Manager + Run Command (Req 1.7). Per the
   * design's Open Decisions, no additional permissions are attached here unless
   * a confirmed later need arises (for example, reading a private-registry
   * secret from SSM Parameter Store) — keeping the instance's blast radius
   * minimal by default.
   */
  private buildInstanceRole(): iam.Role {
    return new iam.Role(this, 'InstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description:
        'SpinSci EC2 instance role: SSM managed-instance access only',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'AmazonSSMManagedInstanceCore',
        ),
      ],
    });
  }
}
