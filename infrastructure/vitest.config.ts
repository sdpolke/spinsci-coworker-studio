import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Scaffolding stage: the stack, constructs and their tests are added by
    // later tasks. Allow `npm test` to succeed before any test files exist.
    passWithNoTests: true,
    include: ["test/**/*.test.ts"],
    environment: "node",
    globals: true,
    // CDK synth + fast-check property tests can run longer than the default.
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
