#!/usr/bin/env node
/**
 * Thin CLI over the pure {@link module:lib/deploy-logic} functions, so the
 * GitHub Actions Deploy_Pipeline (`.github/workflows/deploy-ec2.yml`) invokes
 * the SAME code the property tests cover. The workflow calls, e.g.:
 *
 *   node bin/deploy-cli.ts resolve-target "$TAG"
 *   node bin/deploy-cli.ts image-gate "$TAG"            # exit 0 = available
 *   node bin/deploy-cli.ts ssm-params "$TAG"            # prints JSON parameters
 *   node bin/deploy-cli.ts resolve-timeout "$INPUT"
 *   node bin/deploy-cli.ts is-healthy <status> <body>   # exit 0 = healthy
 *
 * Each subcommand prints its result to stdout and uses the exit code to signal
 * the gate/predicate outcome so the workflow can branch on it with plain shell.
 */
import {
  buildSsmParameters,
  checkImageAvailable,
  deriveImageTag,
  isHealthy,
  resolveHealthTimeout,
  resolveTargetVersion,
  type FetchLike,
} from '../lib/deploy-logic';

/** Node 18+ global fetch adapted to the module's HttpLike contract. */
const nodeFetch: FetchLike = async (url: string) => {
  const res = await fetch(url, { method: 'GET' });
  return {
    ok: res.ok,
    status: res.status,
    json: () => res.json(),
  };
};

async function main(argv: string[]): Promise<number> {
  const [cmd, ...args] = argv;

  switch (cmd) {
    case 'resolve-target': {
      process.stdout.write(resolveTargetVersion(args[0] ?? '') + '\n');
      return 0;
    }
    case 'image-tag': {
      process.stdout.write(deriveImageTag(args[0] ?? '') + '\n');
      return 0;
    }
    case 'image-gate': {
      const result = await checkImageAvailable(args[0] ?? '', nodeFetch);
      process.stdout.write(result.reason + '\n');
      return result.available ? 0 : 1;
    }
    case 'ssm-params': {
      process.stdout.write(
        JSON.stringify(buildSsmParameters(args[0] ?? '')) + '\n',
      );
      return 0;
    }
    case 'resolve-timeout': {
      process.stdout.write(String(resolveHealthTimeout(args[0])) + '\n');
      return 0;
    }
    case 'is-healthy': {
      // args: <status> <jsonBody>
      const status = Number(args[0]);
      let body: unknown;
      try {
        body = JSON.parse(args[1] ?? 'null');
      } catch {
        body = undefined;
      }
      const healthy = isHealthy({
        response: { ok: status >= 200 && status < 300, status, json: async () => body },
        body,
      });
      process.stdout.write(healthy ? 'healthy\n' : 'not-healthy\n');
      return healthy ? 0 : 1;
    }
    default:
      process.stderr.write(
        `Unknown command "${cmd ?? ''}". Expected one of: resolve-target, ` +
          'image-tag, image-gate, ssm-params, resolve-timeout, is-healthy.\n',
      );
      return 2;
  }
}

main(process.argv.slice(2))
  .then((code) => process.exit(code))
  .catch((err) => {
    process.stderr.write(`${err instanceof Error ? err.message : String(err)}\n`);
    process.exit(2);
  });
