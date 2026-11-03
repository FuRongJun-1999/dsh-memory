> **Languages:** [中文](../../ops/发布与治理.md) · English

# Release and repository governance (decision record v1.0)

> This page records governance decisions that are **deliberately this way**, so that later maintainers or an AI do not treat them as defects and "fix" them. Every entry states: the decision / the reason / the conditions under which it changes.

## 1. Release is a single point (one person and a manual OTP): **deliberately maintained**

**Current state**: npm releases are published only by the maintainer in person, running `npm publish` on their own machine, which requires an interactive OTP. **No CI auto-publish is configured**, and no `NPM_TOKEN` secret is added.

**Reasons (maintainer ruling, 2026-10-20)**:

1. The core asset of this project is not the code but the **intelligence theory / theoretical architecture**, and nobody (and no AI) can currently take over that theory;
2. Auto-publishing would strip the "release decision" away from theoretical judgment and create a channel where "a machine ships automatically on a tag", which conflicts with the fact that the theory has too large a blast radius to ship without the single person who understands it acting as the gate;
3. The manual cost of single-point release (one OTP) is far smaller than the theoretical spillover cost of one wrong release.

**Compensating controls in place**:

- `main` branch protection: required checks (`run-tests` / `discipline` / `cogmap` / `workspace-index` / `publish-artifact`), force pushes blocked, branch deletion blocked;
- Pre-release gate: the `prepublishOnly` hook of `npm publish` runs `build && test && gate`;
- Tag discipline: a `v*` tag is placed only on a commit where CI is fully green;
- Release notes must state "known limitations" and must not leave the illusion that "everything looked green".

**Conditions that change this** (re-evaluate automation when any one holds):

1. A second maintainer appears who **understands the theoretical architecture** (not merely someone with repository write access);
2. The release frequency grows until manual OTP is a real bottleneck (currently about 1-2 times per week, which is not a bottleneck);
3. npm offers a mechanism that is equivalent to OTP and also persists "who approved what" as an auditable record.

## 2. `main` protection: **enabled**

- Required status checks: see above;
- `enforce_admins = false`: the maintainer keeps an emergency bypass (which leaves a GitHub audit record), because a single-person project has no second person who could approve instead;
- PR approvals are not required: in a single-person project that would be the formalism of approving your own work; CI carries the quality gate.

## 3. CI concurrency and queuing

Every workflow enables `concurrency` (runs of the same workflow on the same ref are cancelled on a new push), so that several pushes in one day do not queue `run-tests` for more than 30 minutes.

**Paths filtering is deliberately not added to `python-tests`**: the workflow already contains a design comment: the suite spans `md_cg/`, `hive/`, `compiler/`, `swarm/`, and `scripts/`, and a single omission in a paths allowlist would bring back the blind spot where "a change does not enter the gate".

## 4. Dependency updates

dependabot opens one group of PRs per week for `npm` and one for `github-actions` (minor and patch combined, at most 3), turning dependency rot from a pulse of discoveries into small routine fixes.

## 5. Where this does not apply

- This document does not govern the **code quality gate** (that is decided by each workflow and `npm run gate`);
- This document does not cover where release credentials are stored (credentials live only in the maintainer's local keychain; they are not committed to the repository and not added to CI secrets).
