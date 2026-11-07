# Regression Radar

> **Predict risky code changes before they reach production.**

Regression Radar is a pull-request (PR) risk analysis tool that uses a
repository's Git history and the files changed in a PR to identify
patterns that deserve extra review before merging.

It is designed to help developers answer:

-   Does this change touch files that have frequently appeared in
    bug-fix or revert history?
-   Are there files that usually change together but are missing from
    this PR?
-   Which related tests should be considered?
-   Who has relevant contribution history in the affected area?

The goal is not to declare that a PR will fail. Regression Radar
provides **evidence-backed risk signals and recommended actions** so
developers can make better review decisions.

------------------------------------------------------------------------

## Why Regression Radar?

A code change can look correct in isolation and still break behaviour
elsewhere in an application. These failures are commonly called
**regressions**.

Traditional code review and CI checks are essential, but reviewers may
not have the full historical context of a repository. Regression Radar
adds that context at PR time by analysing patterns in previous commits.

### Example

A pull request modifies `payments.ts`.

Repository history shows that:

-   `payments.ts` has appeared in several bug-fix or revert commits.
-   `payments.test.ts` and `refunds.ts` have often changed alongside it.
-   The current PR does not modify those related files.

That does not prove the PR contains a bug. It gives reviewers concrete
reasons to inspect payment tests and refund behaviour before merging.

------------------------------------------------------------------------

## Core Features

### 1. Historical Hotspot Analysis

Analyses Git history to identify files that have frequently appeared in
bug-fix or revert commits.

**Output:** A historical-risk signal for files changed in the current
PR.

### 2. Co-change Pattern Detection

Finds files that have commonly changed together in previous commits.

**Output:** Flags potentially relevant files that are absent from the
current PR.

### 3. Test-gap Hints

Uses repository history and file relationships to identify relevant test
files that may deserve attention.

**Output:** A suggested list of tests to inspect or run. It does not
assume every code change must modify a test file.

### 4. Ownership and Reviewer Hints

Uses contribution and review history, where available, to identify
people with relevant experience in the affected modules.

**Output:** Suggested reviewers based on repository evidence. Git
history alone cannot determine whether someone is currently available or
on leave.

### 5. Explainable Risk Score

Combines deterministic signals into a configurable score from 0 to 100.

**Output:** A prioritisation score with the reasons and evidence behind
it.

> **Important:** The score is not a probability that production will
> fail. It is a risk-prioritisation signal. The scoring model and
> thresholds will be documented and evaluated.

### 6. PR Comment and Recommendations

The planned GitHub integration will publish a concise report containing:

-   Risk score and level
-   Files and historical patterns that triggered the score
-   Potentially missing related files or tests
-   Suggested tests to run
-   Suggested reviewers, when supported by available data
-   A plain-English explanation

An LLM may be used to summarise evidence. It will not be responsible for
inventing the underlying score or findings.

------------------------------------------------------------------------

## How It Works

``` text
Developer opens a Pull Request
              |
              v
       PR data and diff
              |
              v
       Git history analysis
              |
      +-------+--------+----------------+
      |                |                |
      v                v                v
 Historical         Co-change       Test-gap and
 hotspots           patterns        ownership hints
      |                |                |
      +----------------+----------------+
                       |
                       v
             Deterministic scoring
                       |
                       v
          Evidence-based recommendations
                       |
                       v
            Optional AI explanation
                       |
                       v
              GitHub PR report
```

------------------------------------------------------------------------

## Planned Technology Stack

  -----------------------------------------------------------------------
  Area                    Planned technology      Purpose
  ----------------------- ----------------------- -----------------------
  Core analysis           Python                  Git and repository
                                                  analysis

  Git access              Git CLI / GitPython     Commits, diffs and file
                                                  history

  PR integration          GitHub API / GitHub     Read PR changes and
                          Actions                 publish reports

  Backend (if needed)     FastAPI                 Service endpoints and
                                                  integration

  Data analysis           Pandas, NumPy           Historical metrics and
                                                  analysis

  Optional ML             Scikit-learn            Experimental anomaly
                                                  detection

  Explanation             LLM API (optional)      Summarise evidence in
                                                  plain English

  Testing                 Pytest                  Unit and integration
                                                  tests
  -----------------------------------------------------------------------

The initial version will prioritise a **local command-line interface
(CLI)**. GitHub Actions or a GitHub App integration will follow once the
analysis engine works reliably.

------------------------------------------------------------------------

## MVP Scope

The first working version will focus on:

1.  Read a local Git repository.
2.  Accept a target diff or compare a PR branch with its base branch.
3.  Extract changed files and relevant commit history.
4.  Calculate historical hotspot metrics.
5.  Detect co-change relationships.
6.  Identify likely related test files.
7.  Produce a deterministic, explainable risk report in the terminal or
    Markdown.

### Not in the first MVP

-   A full web dashboard
-   Automatic merging or blocking of pull requests
-   Claims that a specific change will definitely cause a production
    incident
-   Reliable detection of developer availability or leave status
-   Complex multi-agent workflows

------------------------------------------------------------------------

## Repository Structure (Initial Plan)

``` text
regression-radar/
├── README.md
├── pyproject.toml
├── .gitignore
├── src/
│   └── regression_radar/
│       ├── __init__.py
│       ├── cli.py
│       ├── git_history.py
│       ├── hotspot.py
│       ├── cochange.py
│       ├── test_gap.py
│       ├── scoring.py
│       └── report.py
├── tests/
│   ├── test_hotspot.py
│   ├── test_cochange.py
│   └── test_scoring.py
├── examples/
└── docs/
```

This is a proposed structure and will evolve as implementation decisions
are made.

------------------------------------------------------------------------

## Team Responsibilities

  -----------------------------------------------------------------------
  Role                                Responsibility
  ----------------------------------- -----------------------------------
  Member 1 --- Git analytics          Git history parser and hotspot
                                      analysis

  Member 2 --- GitHub integration     PR data retrieval and automated PR
                                      reporting

  Member 3 --- Pattern engine         Co-change analysis, test-gap hints
                                      and scoring

  Member 4 --- Validation and         Replay dataset, tests, ownership
  integration                         hints, integration and
                                      documentation
  -----------------------------------------------------------------------

All members should review the scoring design and evaluation results so
that the system remains understandable and reproducible.

------------------------------------------------------------------------

## Evaluation Plan

We will evaluate Regression Radar using historical repository data.

1.  Select a public repository with identifiable bug-fix or revert
    commits.
2.  Reconstruct the repository state and proposed change as they existed
    **before** the fix or revert.
3.  Run Regression Radar using only information available at that point.
4.  Record which historical cases were flagged and which were missed.
5.  Measure false positives: changes flagged as risky that do not
    correspond to the chosen regression labels.
6.  Compare results against simple baselines, such as changed-file count
    or hotspot-only scoring.

We will report the dataset, assumptions, limitations and actual measured
results. We will not claim that a historical replay proves a production
incident would have been prevented.

------------------------------------------------------------------------

## Getting Started

The initial development setup and commands will be added once the CLI
entry point and package configuration are implemented.

For now, clone the repository after it is created:

``` bash
git clone https://github.com/<YOUR-USERNAME>/regression-radar.git
cd regression-radar
```

The first development milestone is to build a local Git-history parser
and generate a basic hotspot report.

------------------------------------------------------------------------

## Project Status

**Current stage:** Project setup and MVP planning.

  Milestone                          Status
  ---------------------------------- -------------
  Project concept and scope          Defined
  Initial repository documentation   In progress
  Git history parser                 Not started
  Historical hotspot engine          Not started
  Co-change detection                Not started
  Deterministic risk scoring         Not started
  CLI report                         Not started
  GitHub PR integration              Planned
  Historical replay evaluation       Planned

------------------------------------------------------------------------

## Principles

-   **Evidence before claims:** Every warning should be traceable to
    repository data.
-   **Deterministic scoring:** The same input and configuration should
    produce the same score.
-   **Human review stays in control:** The tool advises; developers
    decide.
-   **No false certainty:** A risk score is not a failure probability.
-   **Privacy-conscious analysis:** Avoid sending source code or secrets
    to external AI services. Redact sensitive data and make any LLM use
    optional.

------------------------------------------------------------------------

## Contributing

This project is being developed by a four-member hackathon team.
Contribution guidelines, issue templates and branch protections will be
added as the repository takes shape.

For now, use feature branches and pull requests for changes. Keep
commits focused and include tests for analysis logic.

------------------------------------------------------------------------

## License

License to be selected by the project maintainers before public release.
