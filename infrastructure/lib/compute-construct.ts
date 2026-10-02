import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

import { buildUserData } from './user-data';
import { SpinSciEc2StackProps } from './props';

/**
 * Canonical's public SSM parameter for the latest Ubuntu 22.04 LTS (Jammy)
 * amd64 server AMI. Resolving the AMI from this parameter means the instance
 * tracks the latest patched image at deploy time rather than pinning a stale
 * AMI id. The SpinSci setup path is Debian/Ubuntu-oriented (apt Docker install,
 * certbot), so Ubuntu is the primary target. (Design: Compute construct)
 */
const UBUNTU_2204_AMD64_SSM_PARAM =
  '/aws/service/canonical/ubuntu/server/22.04/stable/current/amd64/hvm/ebs-gp2/ami-id';

/**
 * Props for {@link ComputeConstruct}.
 *
 * The construct receives the already-built network and IAM pieces plus the
 * resolved Data_Volume id (so UserData can locate the device). It deliberately
 * does NOT receive the storage construct itself — the stack owns volume
 * attachment so the volume/instance AZ coordination stays in one place.
 */
export interface ComputeConstructProps {
  /** The typed Operator input contract. */
  readonly stackProps: SpinSciEc2StackProps;

  /** The VPC the instance runs in (created or imported by the network construct). */
  readonly vpc: ec2.IVpc;

  /** The Security_Group controlling the instance's ingress/egress. */
  readonly securityGroup: ec2.ISecurityGroup;

  /** The Instance_Profile granting SSM managed-instance access (Req 1.7). */
  readonly instanceProfile: iam.InstanceProfile;

  /**
   * The EBS Data_Volume id, forwarded into UserData so first boot can resolve
   * the device by volume id. The stack passes `storage.volumeId`.
   */
  readonly dataVolumeId: string;
}

/**
 * Provisions the single EC2_Instance, its UserData bootstrap, and the static
 * Elastic_IP.
 *
 * Design references (Req 1.3, 1.4, 1.5, 3):
 *  - Exactly one {@link ec2.Instance} of the configured type (default
 *    `t3.large`) in a single concrete public subnet, with the SG, instance
 *    profile, and generated UserData.
 *  - One {@link ec2.CfnEIP} + {@link ec2.CfnEIPAssociation} so the reported
 *    public IP is the stable Elastic_IP; that same address is passed to
 *    UserData as `SERVER_IP` (Req 1.5, 3.3).
 *
 * The construct exposes {@link availabilityZone} so the stack can create the
 * Data_Volume in the SAME AZ as the instance — an EBS volume can only attach
 * to an instance in its own AZ, so this coordination is essential and is kept
 * explicit rather than inferred.
 */
export class ComputeConstruct extends Construct {
  /** The single EC2_Instance running the SpinSci compose stack. (Req 1.3, 1.4) */
  public readonly instance: ec2.Instance;

  /**
   * The newly-allocated Elastic_IP, when the stack created one. `undefined`
   * when an existing EIP was imported via `eipAllocationId`. (Req 1.5)
   */
  public readonly elasticIp?: ec2.CfnEIP;

  /**
   * The public IP associated with the instance — a CloudFormation `ref` to the
   * created EIP, or the literal imported address. Surfaced as the `PublicIp`
   * stack output. (Req 1.5)
   */
  public readonly publicIp: string;

  /**
   * The Availability Zone the instance was placed in. The stack MUST create the
   * Data_Volume in this AZ so the attachment succeeds at deploy time.
   */
  public readonly availabilityZone: string;

  constructor(scope: Construct, id: string, props: ComputeConstructProps) {
    super(scope, id);

    // Pick ONE concrete public subnet. Selecting a single subnet (rather than a
    // type-based selection) pins the instance to one AZ, which we then reuse for
    // the Data_Volume so the volume and instance share an AZ.
    const publicSubnets = props.vpc.publicSubnets;
    if (publicSubnets.length === 0) {
      throw new Error(
        'ComputeConstruct requires at least one public subnet; the network ' +
          'construct did not provide one.',
      );
    }
    const subnet = publicSubnets[0];
    this.availabilityZone = subnet.availabilityZone;

    // Resolve the public address up front so it can be baked into UserData as
    // SERVER_IP (Req 3.3). Either import an existing EIP (association only, no
    // new allocation) or create a fresh one.
    const existingAllocationId = props.stackProps.eipAllocationId;
    if (existingAllocationId) {
      if (!props.stackProps.eipPublicIp) {
        throw new Error(
          'eipAllocationId was supplied without eipPublicIp; the setup script ' +
            'needs the literal address for SERVER_IP. Provide both.',
        );
      }
      // Import: no CfnEIP resource is created, so a redeploy/destroy never
      // releases the operator-owned address.
      this.publicIp = props.stackProps.eipPublicIp;
    } else {
      this.elasticIp = new ec2.CfnEIP(this, 'ElasticIp', { domain: 'vpc' });
      this.publicIp = this.elasticIp.ref;
    }

    const userData = ec2.UserData.custom(
      buildUserData({
        dataVolumeId: props.dataVolumeId,
        serverIp: this.publicIp,
        certMode: props.stackProps.certMode,
        deployMode: props.stackProps.deployMode,
        letsEncryptEmail: props.stackProps.letsEncryptEmail,
        repo: props.stackProps.githubRepo,
        appSecretArn: props.stackProps.appSecretArn,
        secretRegion: cdk.Stack.of(this).region,
      }),
    );

    // Bind the SSM Instance_Profile from the IAM construct directly. Passing
    // `instanceProfile` (instead of letting the L2 create its own role) means
    // the instance carries exactly AmazonSSMManagedInstanceCore and nothing
    // broader. The L2 forbids passing both `role` and `instanceProfile`. (Req 1.7)
    this.instance = new ec2.Instance(this, 'Instance', {
      vpc: props.vpc,
      vpcSubnets: { subnets: [subnet] },
      instanceType: new ec2.InstanceType(props.stackProps.instanceType),
      machineImage: ec2.MachineImage.fromSsmParameter(
        UBUNTU_2204_AMD64_SSM_PARAM,
        { os: ec2.OperatingSystemType.LINUX },
      ),
      securityGroup: props.securityGroup,
      instanceProfile: props.instanceProfile,
      userData,
      // Require IMDSv2 (token-backed metadata) — hardening best practice.
      requireImdsv2: true,
    });

    // Associate the Elastic_IP with the instance so the reported public IP is
    // the stable EIP — either the imported allocation or the one just created.
    // (Req 1.5)
    new ec2.CfnEIPAssociation(this, 'ElasticIpAssociation', {
      allocationId: existingAllocationId ?? this.elasticIp!.attrAllocationId,
      instanceId: this.instance.instanceId,
    });

    cdk.Tags.of(this.instance).add('Name', `spinsci-${props.stackProps.host}`);
  }
}
