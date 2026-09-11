# AI-assisted engineering with verifiable evidence / 可驗證的 AI 輔助工程流程

This project uses AI as an engineering accelerator for repository analysis, implementation drafts, test design, documentation and failure diagnosis. AI output is never treated as proof by itself. Public claims must trace to code, tests, CI results or an explicitly stated limitation.

本專案將 AI 用於加速 repo 分析、實作草稿、測試設計、文件撰寫與失敗診斷。AI 輸出本身不等於證據；所有公開 claims 都必須連回程式碼、測試、CI 結果，或清楚標示的限制。

OpenAI's official coding guidance recommends running validation that is meaningful and proportional to the change, then broadening it only when failures or unresolved risk justify more work. This repository turns that principle into a repeatable workflow and CI-enforced evidence contract.

OpenAI 官方 coding guidance 建議依變更風險執行有意義且適量的驗證，只有在失敗或風險尚未排除時才擴大檢查範圍。本 repo 將這項原則轉成可重複流程與 CI 強制的 evidence contract。

Source / 來源：[OpenAI model guidance — Testing and verification](https://developers.openai.com/api/docs/guides/latest-model#testing-and-verification)

## What AI contributed / AI 實際協助內容

| Activity | AI contribution | Required evidence |
| --- | --- | --- |
| Repository analysis | Located the highest-impact gaps against the target data-engineering role | File-level implementation plan and scoped commits |
| Implementation | Drafted PostgreSQL, dbt, Terraform, Airflow and CI changes | Reviewed diff, tests and public commit history |
| Test design | Added unit, integration, topology and fresh-checkout contracts | Local test output and GitHub Actions jobs |
| Failure diagnosis | Read public CI state, isolated environment-specific failures and proposed minimal fixes | Failed runs, focused repair commits and a later green run |
| Documentation | Converted implementation details into bilingual architecture and resume evidence | Links to exact files, commits and CI runs |

| 工作 | AI 協助內容 | 必要證據 |
| --- | --- | --- |
| Repo 分析 | 對照目標 data-engineering 職缺，找出影響最大的能力缺口 | 檔案層級實作計畫與 scoped commits |
| 實作 | 協助起草 PostgreSQL、dbt、Terraform、Airflow 與 CI 變更 | 人工檢查的 diff、測試與公開 commit history |
| 測試設計 | 新增 unit、integration、topology 與 fresh-checkout contracts | 本機測試輸出與 GitHub Actions jobs |
| 失敗診斷 | 讀取公開 CI 狀態、定位環境差異並提出最小修正 | 失敗 runs、針對性修正 commits 與後續全綠 run |
| 文件 | 將工程實作整理成雙語架構與履歷證據 | 精確的檔案、commit 與 CI run links |

## Public case study: failed workflow to six green jobs / 公開案例：從 workflow 失敗到六個 jobs 全綠

The sequence below is preserved publicly. It demonstrates the useful part of AI proficiency: creating a short feedback loop, changing course when evidence contradicts an assumption, and refusing to label work complete before the remote environment passes.

以下過程完整保留在公開 GitHub。它展示 AI proficiency 真正有價值的部分：建立短回饋循環、在證據推翻假設時調整方向，以及遠端環境尚未通過前不宣稱完成。

| Evidence | Observation | Engineering response |
| --- | --- | --- |
| [Initial failed run 34539763740](https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/34539763740) | Workflow validation failed before any job was created because `runner.temp` was unavailable in job-level `env`. | [Commit `a75a99d`](https://github.com/Chuanris/mlb-pitch-analytics/commit/a75a99d) changed the metadata path to the allowed `github.workspace` context. |
| [Diagnostic run 34540591806](https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/34540591806) | Four jobs passed. Python lacked PyYAML; Airflow imported the DAG but could not create a DagRun before serialization. | [Commit `56fcafb`](https://github.com/Chuanris/mlb-pitch-analytics/commit/56fcafb) exposed actionable failure annotations; [commit `198bbfc`](https://github.com/Chuanris/mlb-pitch-analytics/commit/198bbfc) added the dependency and serialized the DAG bundle. |
| [Verified run 34540760348](https://github.com/Chuanris/mlb-pitch-analytics/actions/runs/34540760348) | All six jobs completed successfully. | The repository now links the run as evidence while keeping live GCP deployment and a continuously running Airflow scheduler explicitly out of scope. |

Verified jobs / 已驗證 jobs：

- Python and pipeline contracts
- PostgreSQL service-backed integration tests
- dbt build plus idempotent incremental rerun
- BigQuery target parse and MPP manifest contract
- Terraform formatting and two module validations
- Airflow DAG import, topology checks, metadata migration, serialization and 15-task plan-only execution

## Human review and decision boundaries / 人工審核與決策邊界

AI may prepare and verify changes, but the human remains responsible for intent, consequential approvals and the final representation of experience.

AI 可以準備與驗證變更，但專案意圖、具後果的核准，以及履歷經驗的最終表述仍由人負責。

- The user chooses the milestone and authorizes publication.
- Secrets, credentials, generated databases and personal practice notes stay out of Git.
- Existing user changes are preserved unless the user explicitly includes them in scope.
- A dry run proves command planning only; it does not prove a data refresh.
- BigQuery parsing and Terraform validation do not prove a live GCP deployment.
- Airflow plan-only `dag.test()` proves DAG execution semantics, not a continuously running scheduler.
- Resume bullets must describe evidence that actually exists in the repository.

- 使用者決定 milestone 並授權發布。
- Secrets、credentials、生成的 databases 與個人練習筆記不得進入 Git。
- 除非使用者明確納入範圍，既有使用者變更必須保留。
- Dry run 只能證明 command planning，不能代表資料已刷新。
- BigQuery parse 與 Terraform validation 不能代表已完成 live GCP deployment。
- Airflow plan-only `dag.test()` 證明 DAG execution semantics，但不代表 scheduler 正持續運行。
- 履歷 bullet 只能描述 repo 中確實存在的證據。

## Repeatable AI-assisted workflow / 可重複的 AI 協作流程

1. **Define the outcome.** Translate the job requirement into one inspectable repository capability.
2. **Inspect before editing.** Read architecture, tests, dirty-worktree state and security boundaries.
3. **Implement a bounded change.** Keep unrelated user work untouched and use canonical project paths.
4. **Validate proportionally.** Start with focused checks, then run the broader suite when integration risk warrants it.
5. **Use failures as evidence.** Capture the exact failing environment, repair the smallest supported cause and rerun.
6. **Publish only verified claims.** Link commits and CI; label live cloud or production behavior as pending until executed.

1. **定義結果。** 將職缺條件轉成一項可檢查的 repo capability。
2. **先檢查再修改。** 閱讀架構、測試、dirty worktree 與安全邊界。
3. **限定變更範圍。** 保留無關的使用者工作，並使用專案 canonical paths。
4. **依風險驗證。** 先跑 focused checks，integration risk 較高時再跑完整 suite。
5. **把失敗變成證據。** 保存精確的失敗環境、修正最小且有根據的原因，再重新執行。
6. **只發布已驗證 claims。** 連結 commits 與 CI；live cloud 或 production 行為在真正執行前必須標示 pending。

## Prompt patterns that produced reviewable work / 可產生可審核成果的 prompt patterns

These are reusable patterns, not transcripts containing private conversation data.

以下是可重用的 patterns，不是包含私人對話資料的逐字紀錄。

```text
Inspect this repository against these job requirements. Rank the missing
capabilities by resume impact, then implement the highest-value bounded stage.
Preserve unrelated user changes and separate verified evidence from future work.
```

```text
Reproduce the failing CI state first. Identify the smallest supported root cause,
apply a scoped fix, run the relevant local checks, publish only when authorized,
and monitor the remote run to completion.
```

```text
Turn the implementation into a bilingual portfolio explanation. Every capability
claim must link to code, tests, a commit, or a successful CI run. Do not invent
time-saved metrics or claim live cloud execution from a parse, plan, or dry run.
```

## What is deliberately not measured / 刻意不量化的內容

This repository does not claim a percentage productivity gain or hours saved because no controlled baseline was recorded. The defensible evidence is the completed scope, traceable review process, failure-to-fix sequence and passing automation.

本 repo 不宣稱生產力提升百分比或節省時數，因為沒有事先記錄可比較的 controlled baseline。可辯護的證據是已完成範圍、可追溯審核流程、failure-to-fix sequence 與通過的自動化驗證。

## Resume bullet / 履歷 bullet

> Applied AI-assisted software engineering to analyze a legacy analytics repository, implement PostgreSQL, dbt/BigQuery, Terraform and Airflow capabilities, and diagnose Linux CI failures; converted model suggestions into human-reviewed commits and a six-job green GitHub Actions evidence chain without exposing secrets or overstating live-cloud results.

> 使用 AI 輔助工程方法分析既有 analytics repo、實作 PostgreSQL、dbt／BigQuery、Terraform 與 Airflow 能力，並診斷 Linux CI failures；將模型建議轉成經人工審核的 commits 與六個 jobs 全綠的 GitHub Actions 證據鏈，同時避免洩漏 secrets 或誇大 live-cloud 結果。
