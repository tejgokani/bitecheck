# Research

Research date: **2026-10-25**. Sources were found with web search and checked against primary pages or `gh api` where noted. Not finding something in these sources is not proof it doesn't exist.

## 1. The problem is real and named

- Sonar's 2026 State of Code survey, as summarised in several write-ups ([1](https://vibe-coding.academy/blog/ai-code-verification-bottleneck-trust-gap/), [2](https://aiupdatewatch.com/industry-policy/ai-coding-verification-bottleneck/)), reports that **42% of committed code is AI-generated**, and that **96% of developers do not fully trust it**. I'm relying on secondary summaries here and haven't audited Sonar's methodology.
- Qodo's [2026 State of AI Code Quality](https://www.qodo.ai/blog/state-of-ai-code-quality-report-2026/) is titled "Verification Is the New Bottleneck". Both groups it surveyed named review of AI code as their top bottleneck.
- [SRLabs](https://srlabs.de/blog/ai-verification-bottleneck) frames the same bottleneck from the security side.
- **Agents game tests.** [ImpossibleBench](https://arxiv.org/abs/2510.20270) measures how often agents pass deliberately impossible tasks. [Hodoscope](https://arxiv.org/pdf/2604.11072) found that test-assertion editing and special-casing are recurring behaviors.
- **Agents write tests that execute code without checking it.** One Stryker gate ([GGonryun/giveaway.dog#132](https://github.com/GGonryun/giveaway.dog/issues/132)) found a test asserting only `toBeDefined()`. Line coverage looked fine, but its mutation score was 0%.
- **Context files and instructions don't enforce behaviour.** See [Evaluating AGENTS.md, ICLR 2026](https://iclr.cc/virtual/2026/10021142). Enforcement has to come from outside the agent.

## 2. The landscape: every single technique exists in isolation

In late 2026 almost every single-feature idea in agent tooling has a weekend repository, most with 0–20 stars. The table groups what I found by technique.

| Technique | Examples found | What's missing |
|---|---|---|
| LLM PR reviewers | CodeRabbit, Greptile, Qodo Merge, Copilot review ([comparison](https://www.morphllm.com/github-ai-code-review)) | AI judging AI. No execution evidence. Greptile's runtime mode TREX is in paid beta |
| Execution-based PR review (commercial) | [Qodex](https://qodex.ai/product/ai-code-review) (API/UI tests on previews) | Closed, hosted, app-level only |
| Diff-pattern test-weakening guards | AssertVet, agent-diff-guard, test-guard, Assertion Guardian, goalpost (syntaxixr) | Static. They can't tell a legitimate test fix from a moved goalpost |
| Old-tests-on-new-code / fail-to-pass | [fliptest](https://github.com/tejgokani/fliptest) (same author), claim-check (MuhammadMoeezKhan), plus per-project CI scripts | One technique each |
| Agent claim checkers | [backcheck](https://github.com/VectorInstitute/backcheck), [receipts](https://github.com/Jasowills/receipts), [agent-receipts](https://github.com/0xelitesystem/agent-receipts), 3× "claim-check" plugins | Mostly Claude-only. They check transcripts, not the code |
| Behavioural diff | [RealDiff](https://github.com/issacnitin/RealDiff), [bdiff](https://github.com/matrixjnr/bdiff), [BehaviorDiff](https://github.com/NewBot62/BehaviorDiff), goalie, CrossHair `diffbehavior`, Hypothesis ghostwriter `--equivalent` | Separate tools, not tied to test quality |
| Mutation testing, per language | Stryker (JS), mutmut (Py), PIT (Java), cargo-mutants (`--in-diff`), go-mutesting | Different setup per language. Agents can't use them uniformly |
| Mutation testing, multi-language | [universalmutator](https://agroce.github.io/fse24.pdf) (regex/Comby, research), [mewt / MuTON](https://blog.trailofbits.com/2026/04/01/mutation-testing-for-the-agentic-era/) (Trail of Bits), Mutahunter (LLM-based), Mull (LLVM) | See §3 |
| Diff-scoped mutation for agent PRs | per-repo scripts: [ai-pr-confidence#26](https://github.com/shalinichitrapu/ai-pr-confidence/pull/26), [agentic-mermaid#355](https://github.com/adewale/agentic-mermaid/issues/355), [SpecStory write-up](https://specstory.com/learning/test-quality/diff-scoped-mutation-testing); Google's in-review mutation testing (Petrović et al., 2021) | No reusable, language-neutral tool. No agent loop |
| Slopsquatting / hallucinated deps | Slopstop, SlopGuard, [arXiv 2608.23897](https://arxiv.org/pdf/2608.23897) | Pre-install only. Not tied to the agent's diff |
| Multi-agent conflict detection | [Clash](https://github.com/clash-sh/clash), [Foremerge](https://github.com/naw103/foremerge), MCP Agent Mail, agent-lease-mcp, [Claim Plane](https://arxiv.org/pdf/2607.21909) | Out of scope for v1 |
| Token-compression proxies | Headroom, promptreduce, tamp, ClaudeSlim, claude-code-cache-fix | Saturated, so this direction was rejected |
| "Benchmark agents on your repo" | selfbench, repo2bench, RepoTrials, repo-to-bench, inhouse-agent-bench | Saturated, so this direction was rejected |

## 3. The closest serious prior art: Trail of Bits mewt

From the [Trail of Bits post](https://blog.trailofbits.com/2026/04/01/mutation-testing-for-the-agentic-era/) (2026-04-01), mewt is a language-agnostic mutation core built on tree-sitter. It supports Solidity, Rust, Go and more, and it powers MuTON. Agent support comes as skills that help an agent configure a campaign and triage its results.

**Gaps they state themselves:**

- Performance is "the biggest obstacle".
- Semantic no-op mutants need deeper language understanding.
- On mutation-driven test generation, and on agents encoding bugs into tests: "Stay tuned."

**Not in the post:** diff-scoping, and an enforcement loop that feeds survivors back to the agent from a hook.

## 4. Agent hook contracts (verified from official docs, 2026-10-25)

| Agent | Event | Make the agent continue | Loop guard | Final message on stdin |
|---|---|---|---|---|
| Claude Code | `Stop` | exit 2 + stderr | `stop_hook_active` | via `transcript_path` |
| Codex CLI ([docs](https://learn.chatgpt.com/docs/hooks)) | `Stop` | exit 2 + stderr, or `{"decision":"block","reason":...}` | `stop_hook_active` | `last_assistant_message` |
| Gemini CLI ([docs](https://geminicli.com/docs/hooks/reference)) | `AfterAgent` | exit 2 + stderr, or `{"decision":"deny","reason":...}` | `stop_hook_active` | `prompt_response` (+ `prompt`) |

All three converged on the same continuation contract, so one adapter covers them. The local session formats were inspected on this machine:

- **Claude Code:** `~/.claude/projects/<cwd-slug>/<session>.jsonl`, with `type: assistant` records carrying `message.content[]`.
- **Codex:** `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, with `session_meta.payload.cwd` and `event_msg/task_complete.payload.last_agent_message`.

## 5. Candidates scored

Scoring: weights in %, scores 1–5.

| Candidate | Significance 20 | Differentiation 20 | Feasibility 15 | Adoption 15 | DX 10 | Offline 10 | Demo 5 | Extensibility 5 | Total |
|---|---|---|---|---|---|---|---|---|---|
| **Unified execution-evidence verifier, centred on diff-scoped multi-language mutation plus agent feedback loop (bitecheck)** | 5 | 4 | 3 | 4 | 4 | 5 | 5 | 5 | **4.25** |
| Semantic conflict oracle for parallel agents | 4 | 3 | 2 | 3 | 3 | 5 | 4 | 4 | 3.40 |
| Own-repo agent benchmark | 4 | 1 | 3 | 3 | 3 | 4 | 4 | 4 | 3.05 |
| Token-compression proxy | 5 | 1 | 4 | 4 | 4 | 4 | 4 | 3 | 3.55 |
| Behavioural diff only | 4 | 2 | 3 | 3 | 3 | 5 | 4 | 3 | 3.30 |
| Claim checker only | 3 | 1 | 5 | 3 | 4 | 5 | 4 | 2 | 3.25 |
| Provenance/attestation ledger for AI code | 3 | 3 | 3 | 2 | 2 | 5 | 2 | 4 | 2.95 |
| Agent-file linter | 2 | 1 | 5 | 3 | 4 | 5 | 3 | 2 | 2.85 |

**Why the winner wins.**

- **Mutation testing on the changed lines** is the strongest available evidence that an agent's tests actually check its change. Coverage only proves the lines ran; a killed mutant proves a test noticed the code was wrong.
- **No existing tool** in the sources examined combines three things: language-neutral operation with your own test command, diff scoping, and a hook that sends survivors back to Claude Code, Codex and Gemini.
- **Two of the gaps** ("mutation-driven test generation", performance) are named as open problems by the most serious prior art.

**Backup:** the semantic conflict oracle.
