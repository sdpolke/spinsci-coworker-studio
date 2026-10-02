import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as dlm from 'aws-cdk-lib/aws-dlm';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

import { DATA_VOLUME_MAX_GIB, DATA_VOLUME_MIN_GIB } from './props';

/**
 * The tag key/value used to identify the Data_Volume. The DLM backup policy
 * (Req 6.5) targets volumes carrying this tag, and the UserData device-resolver
 * can also use it. Kept as a construct-level constant so the stack and tests
 * reference one source of truth.
 */
export const DATA_VOLUME_TAG_KEY = 'spinsci:data-volume';
export const DATA_VOLUME_TAG_VALUE = 'true';

/**
 * Input contract for {@link StorageConstruct}.
 *
 * The construct is deliberately self-contained: it creates the standalone
 * Data_Volume and its DLM backup policy regardless of whether the owning stack
 * has an instance yet. If an `instance` is supplied, the construct also creates
 * the {@link ec2.CfnVolumeAttachment} wiring the volume to that instance at the
 * deterministic device name; otherwise the stack (task 8.1) can create the
 * attachment itself using the exposed {@link StorageConstruct.volume} /
 * {@link StorageConstruct.volumeId} and {@link StorageConstruct.DEVICE_NAME}.
 */
export interface StorageConstructProps {
  /**
   * The Availability Zone the Data_Volume must be created in. An EBS volume and
   * the instance it attaches to must live in the same AZ, so the AZ is passed
   * in from the compute/stack layer (the instance's AZ) rather than inferred.
   */
  readonly availabilityZone: string;

  /**
   * The Data_Volume size in GiB. Validated here against the inclusive bounds
   * [{@link DATA_VOLUME_MIN_GIB}, {@link DATA_VOLUME_MAX_GIB}] = [1, 16384]
   * (Req 1.6 / Property 5). The entrypoint (task 8.2) also validates this; the
   * construct re-validates so it is self-defending.
   */
  readonly dataVolumeSizeGiB: number;

  /**
   * Optional instance to attach the Data_Volume to. When provided, the construct
   * creates the {@link ec2.CfnVolumeAttachment} at {@link StorageConstruct.DEVICE_NAME}.
   * When omitted, the stack wires the attachment itself. (Req 1.6, 6.4)
   */
  readonly instance?: ec2.Instance;
}

/**
 * Provisions the persistent Data_Volume for the single-instance SpinSci
 * deployment, plus its EBS-snapshot backup policy.
 *
 * Design references:
 * - A standalone `gp3`, encrypted EBS {@link ec2.Volume} with RemovalPolicy
 *   RETAIN so instance replacement never deletes/recreates it (Req 6.1, 6.4;
 *   Property 2). Because it is a standalone volume + {@link ec2.CfnVolumeAttachment}
 *   (not an inline instance block device), its lifecycle is decoupled from the
 *   instance.
 * - A Data Lifecycle Manager (DLM) policy that snapshots the volume daily,
 *   targeting it by the `spinsci:data-volume` tag, with a retention count
 *   (Req 6.5). DLM runs under a minimal IAM service role created here.
 *
 * This construct intentionally does NOT create the instance, networking, the
 * instance profile, or the OIDC role — those belong to other constructs.
 */
export class StorageConstruct extends Construct {
  /**
   * Deterministic device name the Data_Volume attaches at. The Linux kernel may
   * surface it as `/dev/xvdf` or an NVMe alias; UserData resolves the real
   * device by matching the EBS volume id rather than hard-coding this path.
   */
  public static readonly DEVICE_NAME = '/dev/sdf';

  /** The standalone Data_Volume (EBS). */
  public readonly volume: ec2.Volume;

  /** Convenience accessor for the Data_Volume id (used by UserData/stack). */
  public readonly volumeId: string;

  /**
   * The volume attachment, present only when an `instance` was supplied to the
   * constructor. When undefined, the stack is responsible for attaching.
   */
  public readonly attachment?: ec2.CfnVolumeAttachment;

  /** The DLM snapshot lifecycle policy backing up the Data_Volume (Req 6.5). */
  public readonly backupPolicy: dlm.CfnLifecyclePolicy;

  constructor(scope: Construct, id: string, props: StorageConstructProps) {
    super(scope, id);

    this.validateSize(props.dataVolumeSizeGiB);

    // Data_Volume: standalone, gp3, encrypted, in the instance's AZ. (Req 1.6, 6.1)
    this.volume = new ec2.Volume(this, 'DataVolume', {
      availabilityZone: props.availabilityZone,
      size: cdk.Size.gibibytes(props.dataVolumeSizeGiB),
      volumeType: ec2.EbsDeviceVolumeType.GP3,
      encrypted: true,
    });

    // Never destroy or replace the volume on stack update/instance replacement.
    // applyRemovalPolicy RETAIN sets both DeletionPolicy and UpdateReplacePolicy
    // to Retain. (Req 6.1, 6.4; Property 2)
    this.volume.applyRemovalPolicy(cdk.RemovalPolicy.RETAIN);

    // Tag the volume so the DLM policy (and device resolution) can find it.
    cdk.Tags.of(this.volume).add(DATA_VOLUME_TAG_KEY, DATA_VOLUME_TAG_VALUE);

    this.volumeId = this.volume.volumeId;

    // Attach to the instance via a separate attachment resource (NOT an inline
    // block device) so the volume lifecycle stays independent. (Req 6.4)
    if (props.instance) {
      this.attachment = new ec2.CfnVolumeAttachment(this, 'DataVolumeAttachment', {
        device: StorageConstruct.DEVICE_NAME,
        instanceId: props.instance.instanceId,
        volumeId: this.volume.volumeId,
      });
    }

    // DLM backup policy: daily EBS snapshots of the Data_Volume. (Req 6.5)
    this.backupPolicy = this.createBackupPolicy();
  }

  /**
   * Validate the Data_Volume size against the inclusive [1, 16384] GiB bounds.
   * Throws an Error naming the bound when outside range. (Req 1.6 / Property 5)
   */
  private validateSize(sizeGiB: number): void {
    if (
      !Number.isInteger(sizeGiB) ||
      sizeGiB < DATA_VOLUME_MIN_GIB ||
      sizeGiB > DATA_VOLUME_MAX_GIB
    ) {
      throw new Error(
        `dataVolumeSizeGiB must be an integer within [${DATA_VOLUME_MIN_GIB}, ${DATA_VOLUME_MAX_GIB}] GiB, got ${sizeGiB}`,
      );
    }
  }

  /**
   * Create a Data Lifecycle Manager (DLM) policy that takes daily EBS snapshots
   * of the Data_Volume (targeted by the `spinsci:data-volume` tag) and retains
   * the most recent 7. DLM requires a service IAM role; a minimal one scoped to
   * the DLM service principal with the AWS managed DLM policy is created here.
   * (Req 6.5)
   */
  private createBackupPolicy(): dlm.CfnLifecyclePolicy {
    // Minimal, least-privilege service role for DLM. The AWS managed policy
    // `AWSDataLifecycleManagerServiceRole` grants exactly the EBS
    // snapshot create/delete/tag permissions DLM needs — nothing more.
    const dlmRole = new iam.Role(this, 'DlmServiceRole', {
      assumedBy: new iam.ServicePrincipal('dlm.amazonaws.com'),
      description: 'Service role for the SpinSci Data_Volume DLM snapshot policy (Req 6.5)',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          'service-role/AWSDataLifecycleManagerServiceRole',
        ),
      ],
    });

    return new dlm.CfnLifecyclePolicy(this, 'DataVolumeBackupPolicy', {
      description: 'SpinSci Data_Volume daily EBS snapshots',
      state: 'ENABLED',
      executionRoleArn: dlmRole.roleArn,
      policyDetails: {
        policyType: 'EBS_SNAPSHOT_MANAGEMENT',
        resourceTypes: ['VOLUME'],
        // Target the Data_Volume by its identifying tag. (Req 6.5)
        targetTags: [
          { key: DATA_VOLUME_TAG_KEY, value: DATA_VOLUME_TAG_VALUE },
        ],
        schedules: [
          {
            name: 'DailySnapshots',
            createRule: {
              // Daily snapshots at a fixed UTC time.
              interval: 24,
              intervalUnit: 'HOURS',
              times: ['03:00'],
            },
            retainRule: {
              // Keep the most recent 7 snapshots.
              count: 7,
            },
            copyTags: true,
          },
        ],
      },
    });
  }
}
