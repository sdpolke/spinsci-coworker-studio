---
inclusion: fileMatch
fileMatchPattern: '**/{cdk.json,cdk.context.json,*.cdk.ts,*stack*.ts,*stack*.py,app.py}'
---

# AWS CDK — project conventions (voiceagent_v2)

Workspace-scoped guidance for AWS CDK work in THIS project only. Not global.

## AWS credentials / profile

- Use the AWS profile **`032398581868_Developer`** for all AWS CLI, CDK, and
  SDK calls made for this project (account `032398581868`).
- Pass it explicitly on every command, e.g.:
  - `AWS_PROFILE=032398581868_Developer cdk synth`
  - `AWS_PROFILE=032398581868_Developer cdk deploy`
  - `aws --profile 032398581868_Developer sts get-caller-identity`
- The profile uses static access keys from the shared credentials file. It has
  **no region configured on the profile itself** — always set the region
  explicitly (see below).

## Default CDK language

- **TypeScript.** The infrastructure project under `infrastructure/` is a
  standalone Node/TypeScript CDK app (`aws-cdk-lib`, `constructs`, `vitest` +
  `fast-check` property tests, strict `tsconfig`). CDK is authored in TS here
  regardless of the app's Python stack — the infra workspace is isolated and
  shares no code with `api/`.

## Default deploy region

- **`us-east-2`** — the deploy region for this project.
  Set it explicitly on commands and stacks, e.g. `CDK_DEFAULT_REGION=us-east-2`
  or `AWS_REGION=us-east-2`, and set `env` on the stack
  (`env: { account: "032398581868", region: "us-east-2" }`).
- Note: the Agent Toolkit CLI (`aws agent-toolkit ...`) itself only works in
  `us-east-1`; that is unrelated to where CDK stacks deploy.

## Tooling installed on this machine

- `cdk` CLI: v2.x (installed globally via `npm i -g aws-cdk`).
- `aws` CLI: v2.35+.
- The `aws-cdk` Agent Toolkit skill is installed in Kiro (`~/.kiro/skills/aws-cdk`).

## Secrets handling (EC2 stack)

- External third-party API keys (Cartesia, Groq, Deepgram, OpenAI, Langfuse,
  PostHog, Sentry, ...) live in **one Secrets Manager JSON secret**, fetched at
  **container start** by `scripts/fetch_secrets.sh` via the EC2 instance role.
  **Never bake secrets into an image at build time.**
- Box-internal secrets (`OSS_JWT_SECRET`, DB/Redis/MinIO passwords,
  `TURN_SECRET`) stay generated locally by `setup_remote.sh` into `.env` on the
  data volume — do NOT move these to Secrets Manager.
- CDK **imports** the secret by complete ARN (`-c appSecretArn=...`) and grants
  least-privilege `secretsmanager:GetSecretValue` to the **instance role only**,
  scoped to that ARN. Secret material never enters CloudFormation. The OIDC
  deploy role gets no secret access. Optional `-c kmsKeyArn=...` for a CMK.

## Guardrails

- Never commit AWS credentials or secrets to the repo.
- Treat `cdk deploy`, `cdk destroy`, and any change touching live/prod resources
  as high-risk: show the plan / `cdk diff` and confirm before applying.
