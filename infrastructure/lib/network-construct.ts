import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

import { SpinSciEc2StackProps } from './props';

/**
 * Networking construct for the SpinSci single-instance EC2 deployment.
 *
 * Responsibilities (Req 1.1, 1.2, 2.1–2.6):
 *  - Provide the VPC the instance runs in: either import an existing VPC by id
 *    (Req 1.2) or create a new single-AZ, NAT-free VPC with one public subnet
 *    (Req 1.1).
 *  - Select the public subnet(s) the instance is launched into so it receives a
 *    public IP (Req 1.1).
 *  - Create the Security_Group that opens exactly the ports the SpinSci stack
 *    needs and never opens SSH (Req 2.1–2.6, Property 1).
 *
 * This construct does NOT create the instance, Elastic IP, EBS volume, IAM
 * resources, or UserData — those live in sibling constructs (tasks 4–8).
 */

/**
 * Subset of {@link SpinSciEc2StackProps} the networking construct depends on.
 * Narrowing to just `vpcId` keeps the construct decoupled from unrelated inputs
 * (instance type, storage size, OIDC, etc.) and makes it trivial to drive from
 * property tests.
 */
export interface NetworkConstructProps {
  /**
   * Existing VPC id to import. When set, the construct imports that VPC via
   * `Vpc.fromLookup` and reuses an existing public subnet; when omitted, it
   * creates a new VPC with a single public subnet. (Req 1.1, 1.2)
   */
  readonly vpcId?: SpinSciEc2StackProps['vpcId'];
}

export class NetworkConstruct extends Construct {
  /** The VPC the EC2_Instance runs in (created or imported). (Req 1.1, 1.2) */
  public readonly vpc: ec2.IVpc;

  /**
   * The public subnet selection the instance is launched into so it receives a
   * public IP address. (Req 1.1)
   */
  public readonly vpcSubnets: ec2.SubnetSelection;

  /**
   * The Security_Group controlling ingress/egress for the EC2_Instance.
   * (Req 2.1–2.6)
   */
  public readonly securityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: NetworkConstructProps) {
    super(scope, id);

    this.vpc = this.resolveVpc(props.vpcId);
    this.vpcSubnets = { subnetType: ec2.SubnetType.PUBLIC };

    this.securityGroup = this.buildSecurityGroup(this.vpc);
  }

  /**
   * Import an existing VPC by id, or create a new single-AZ, NAT-free VPC with a
   * single public subnet.
   *
   * When importing (Req 1.2), the imported VPC must expose at least one public
   * subnet so the instance can receive a public IP (Req 1.1). If it does not,
   * synthesis fails fast with a clear error rather than silently placing the
   * instance where it cannot be reached.
   */
  private resolveVpc(vpcId: SpinSciEc2StackProps['vpcId']): ec2.IVpc {
    if (vpcId) {
      const imported = ec2.Vpc.fromLookup(this, 'Vpc', { vpcId });

      if (imported.publicSubnets.length === 0) {
        throw new Error(
          `Imported VPC "${vpcId}" has no public subnet; the SpinSci EC2 ` +
            'instance requires a public subnet so it can receive a public IP. ' +
            'Supply a VPC with at least one public subnet, or omit vpcId to ' +
            'let the stack create one.',
        );
      }

      return imported;
    }

    // New VPC: single AZ is sufficient for a single-instance topology, and
    // natGateways: 0 avoids idle NAT cost since the public subnet reaches the
    // internet directly through the internet gateway. (Req 1.1)
    return new ec2.Vpc(this, 'Vpc', {
      maxAzs: 1,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
        },
      ],
    });
  }

  /**
   * Build the Security_Group opening exactly the SpinSci stack's ports from any
   * IPv4 source, with no SSH ingress.
   *
   * Ingress (Req 2.1–2.4):
   *  - TCP 80 (http)
   *  - TCP 443 (https)
   *  - TCP + UDP 3478 (coturn STUN/TURN)
   *  - TCP + UDP 5349 (coturn STUN/TURN over TLS/DTLS)
   *  - UDP 49152–49200 (coturn media relay range)
   *
   * No port 22 (TCP or UDP) rule is ever added (Req 2.5, 2.6, Property 1):
   * administrative shell access is provided by AWS Systems Manager Session
   * Manager, not inbound SSH.
   *
   * `allowAllOutbound: true` lets the instance reach SSM endpoints, Docker
   * Hub/GHCR, and Let's Encrypt over the internet gateway.
   */
  private buildSecurityGroup(vpc: ec2.IVpc): ec2.SecurityGroup {
    const securityGroup = new ec2.SecurityGroup(this, 'SecurityGroup', {
      vpc,
      description: 'SpinSci EC2 instance ingress (http/https + coturn); no SSH',
      allowAllOutbound: true,
    });

    const anyIpv4 = ec2.Peer.anyIpv4();

    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.tcp(80),
      'http (nginx)',
    );
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.tcp(443),
      'https (nginx)',
    );

    // coturn STUN/TURN signalling on 3478 (both transports).
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.tcp(3478),
      'coturn stun/turn (tcp)',
    );
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.udp(3478),
      'coturn stun/turn (udp)',
    );

    // coturn STUN/TURN over TLS/DTLS on 5349 (both transports).
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.tcp(5349),
      'coturn stun/turn over tls (tcp)',
    );
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.udp(5349),
      'coturn stun/turn over tls (udp)',
    );

    // coturn media relay port range (UDP only).
    securityGroup.addIngressRule(
      anyIpv4,
      ec2.Port.udpRange(49152, 49200),
      'coturn relay range (udp)',
    );

    // Intentionally NO port 22 ingress (Req 2.5, 2.6): administrative shell
    // access is via AWS Systems Manager Session Manager, not inbound SSH.

    return securityGroup;
  }
}
