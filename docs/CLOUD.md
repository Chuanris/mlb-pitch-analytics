# GCP deployment evidence / GCP 部署證據

The repository now contains a deployable, keyless Google Cloud path rather than only a BigQuery dbt profile. The implementation provisions private GCS storage, BigQuery medallion datasets, split infrastructure/runtime identities, remote Terraform state, and a manually approved GitHub Actions pipeline.

本專案現在不只有 BigQuery dbt profile，也包含可部署、無長效金鑰的 Google Cloud 路徑：私有 GCS 儲存、BigQuery Medallion datasets、分離的 infrastructure／runtime identities、remote Terraform state，以及需人工核准的 GitHub Actions pipeline。

## Evidence map / 證據地圖

| Requirement | Inspectable evidence |
| --- | --- |
| Cloud storage | Versioned GCS Bronze bucket, uniform bucket-level access, enforced public-access prevention, scoped lifecycle rule |
| Cloud security | GitHub OIDC federation restricted by repository and branch; no JSON key; separate deploy/runtime accounts; dataset- and bucket-scoped data access |
| MPP execution | BigQuery datasets, dbt merge incremental model, daily partition, two clustering fields, eight configurable threads |
| Cost awareness | Manual-only apply, explicit `DEPLOY` guard, plan-first workflow, 100 MB query cap, dry-run bytes and billed-byte evidence |
| CI/CD | Credential-free Terraform format/validate in CI; protected `gcp-dev` environment for live plan/apply |
| Reproducibility | Deterministic 12-row source fixture, SHA-256 landing manifest, two consecutive dbt builds, machine-readable verification artifact |

| 條件 | Repo 內可檢查證據 |
| --- | --- |
| Cloud storage | 有版本控制的 GCS Bronze bucket、uniform bucket-level access、強制 public-access prevention、限定範圍的 lifecycle rule |
| Cloud security | GitHub OIDC 限定 repository 與 branch、不使用 JSON key、分離部署／執行帳號、dataset／bucket 範圍資料權限 |
| MPP execution | BigQuery datasets、dbt merge incremental、每日分區、兩個 clustering fields、可調整的八 threads |
| 成本意識 | 只允許手動 apply、明確 `DEPLOY` guard、先 plan、100 MB query cap、dry-run 與 billed-byte 證據 |
| CI/CD | CI 不需憑證即可 Terraform format／validate；live plan／apply 受 `gcp-dev` environment 保護 |
| 可重現性 | Deterministic 12-row source fixture、SHA-256 landing manifest、連續兩次 dbt build、machine-readable verification artifact |

## Claim boundary / 可宣稱範圍

Until a successful `apply` workflow artifact exists, say **"implemented a deployable BigQuery/GCS platform with credential-free contract tests"**, not **"deployed a production BigQuery platform."** A successful run adds evidence of real authentication, resource creation, BigQuery SQL execution, data tests, incremental idempotency, and measured scan/slot statistics. It still remains a development-scale portfolio workload.

在成功的 `apply` workflow artifact 出現前，履歷應寫「implemented a deployable BigQuery/GCS platform with credential-free contract tests」，不要寫「deployed a production BigQuery platform」。成功執行後，才能補充真實 authentication、resource creation、BigQuery SQL execution、data tests、incremental idempotency 與 scan／slot metrics；即使如此，它仍是開發規模的作品集 workload。

Setup and teardown cautions are in [the Terraform guide](../infra/terraform/README.md). Transformation details are in [the dbt guide](DBT.md).

設定與拆除注意事項請見 [Terraform 指南](../infra/terraform/README.md)；轉換細節請見 [dbt 指南](DBT.md)。
