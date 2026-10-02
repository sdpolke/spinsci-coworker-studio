import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

import { ComputeConstruct } from './compute-construct';
import { IamConstruct } from './iam-construct';
import { NetworkConstruct } from './network-construct';
import { SpinSciEc2StackProps } from './props';
import { StorageConstruct } from './storage-construct';

/**
 * The single CloudFormation stack provisioning the SpinSci single-instance EC2
 * deployment.
 *
 * It composes four focused constructs and wires them together (Req 1, 2, 5, 6):
 *  - {@link NetworkConstruct}: VPC (create or import) + Security_Group.
 *  - {@link IamConstruct}: SSM Instance_Profile + GitHub OIDC provider; the
 *    OIDC_Role is added after the instance exists so its `ssm:SendCommand`
 *    grant can be scoped to the instance ARN.
 *  - {@link ComputeConstruct}: the single EC2_Instance, its UserData, and the
 *    Elastic_IP. Exposes the chosen AZ.
 *  - {@link StorageConstruct}: the standalone RETAIN Data_Volume (created in the
 *    instance's AZ) + DLM backup; the stack creates the attachment.
 *
 * The critical cross-construct invariant handled here: the Data_Volume is
 * created in the SAME AZ the compute construct placed the instance, because an
 * EBS volume can only attach to an instance in its own AZ.
 */
export class SpinSciEc2Stack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SpinSciEc2StackProps) {
    super(scope, id, props);

    // --- Networking: VPC + Security_Group (Req 1.1, 1.2, 2) ------------------
    const network = new NetworkConstruct(this, 'Network', {
      vpcId: props.vpcId,
    });

    // --- IAM: SSM instance profile + GitHub OIDC provider (Req 1.7, 5.1) -----
    const iam = new IamConstruct(this, 'Iam', { stackProps: props });

    // Resolve the AZ before creating either the volume or the instance. There
    // is a dependency cycle in principle (storage needs the instance's AZ; the
    // instance's UserData needs the volume id), but the AZ is a property of the
    // concrete public subnet the network construct already fixed — it does not
    // require the instance to exist. So: derive the AZ from the subnet, create
    // storage in that AZ, then compute (which consumes the volume id), then
    // attach. The compute construct independently picks publicSubnets[0], and
    // the guard below asserts the two agree.
    const subnetAz = network.vpc.publicSubnets[0]?.availabilityZone;
    if (!subnetAz) {
      throw new Error(
        'The VPC exposes no public subnet; cannot place the instance or its ' +
          'Data_Volume. Supply a VPC with a public subnet or omit vpcId.',
      );
    }

    // --- Storage: Data_Volume in the instance's AZ + DLM backup (Req 1.6, 6) -
    const storage = new StorageConstruct(this, 'Storage', {
      availabilityZone: subnetAz,
      dataVolumeSizeGiB: props.dataVolumeSizeGiB,
    });

    const compute = new ComputeConstruct(this, 'Compute', {
      stackProps: props,
      vpc: network.vpc,
      securityGroup: network.securityGroup,
      instanceProfile: iam.instanceProfile,
      dataVolumeId: storage.volumeId,
    });

    // Guard the AZ invariant: the subnet AZ we gave storage must match the AZ
    // the compute construct actually placed the instance in. They are both
    // derived from publicSubnets[0], so this is belt-and-suspenders, but it
    // turns a silent deploy-time attachment failure into a clear synth error.
    if (compute.availabilityZone !== subnetAz) {
      throw new Error(
        `Data_Volume AZ (${subnetAz}) does not match instance AZ ` +
          `(${compute.availabilityZone}); the EBS attachment would fail at ` +
          'deploy time.',
      );
    }

    // --- Attach the Data_Volume to the instance (Req 6.4) --------------------
    // Separate CfnVolumeAttachment (not an inline block device) so the volume's
    // RETAIN lifecycle stays independent of the instance.
    new ec2.CfnVolumeAttachment(this, 'DataVolumeAttachment', {
      device: StorageConstruct.DEVICE_NAME,
      instanceId: compute.instance.instanceId,
      volumeId: storage.volumeId,
    });

    // --- OIDC_Role: scoped to this instance now that it exists (Req 5.4) -----
    const deployRole = iam.addDeployRole(compute.instance.instanceId);

    // --- App secret: least-privilege read for the instance role (optional) ---
    // Imported by ARN; secret material never enters CloudFormation. Only the
    // instance role gets access — never the OIDC deploy role.
    if (props.appSecretArn) {
      iam.addAppSecretAccess(props.appSecretArn, props.kmsKeyArn);
    }

    // --- Stack outputs -------------------------------------------------------
    new cdk.CfnOutput(this, 'PublicIp', {
      value: compute.publicIp,
      description: 'Static Elastic IP associated with the SpinSci instance',
    });
    new cdk.CfnOutput(this, 'InstanceId', {
      value: compute.instance.instanceId,
      description: 'EC2 instance id (SSM target for the Deploy_Pipeline)',
    });
    new cdk.CfnOutput(this, 'DataVolumeId', {
      value: storage.volumeId,
      description: 'EBS Data_Volume id (RETAIN; holds Docker data + .env)',
    });
    if (deployRole) {
      new cdk.CfnOutput(this, 'DeployRoleArn', {
        value: deployRole.roleArn,
        description:
          'OIDC role ARN assumed by the GitHub Actions Deploy_Pipeline',
      });
    }
  }
}
