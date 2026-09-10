# Google Cloud infrastructure / Google Cloud 基礎設施

This directory provisions a keyless GitHub-to-Google Cloud deployment path and the GCS/BigQuery resources used by the dbt medallion pipeline. It is split into two states so the deployment identity cannot accidentally manage its own trust boundary during routine releases.

本目錄建立無長效金鑰的 GitHub-to-Google Cloud 部署路徑，以及 dbt Medallion 管線使用的 GCS／BigQuery 資源。它拆成兩份 state，使日常部署身份不會在一般 release 中意外修改自己的信任邊界。

## Modules / 模組

| Module | Purpose | Identity |
| --- | --- | --- |
| `bootstrap/` | Enables APIs, creates the versioned Terraform-state bucket, GitHub Workload Identity Federation, Terraform deployer, and dbt runtime identity | A human/project bootstrap identity; run rarely |
| `platform/` | Creates the private Bronze landing bucket, five BigQuery datasets, and dataset/bucket-scoped runtime grants | Short-lived GitHub OIDC Terraform identity |

| 模組 | 用途 | 使用身份 |
| --- | --- | --- |
| `bootstrap/` | 啟用 APIs，建立有版本控制的 Terraform state bucket、GitHub Workload Identity Federation、Terraform deployer 與 dbt runtime identity | 人工／專案 bootstrap identity；極少執行 |
| `platform/` | 建立私有 Bronze landing bucket、五個 BigQuery datasets，以及 dataset／bucket 範圍的 runtime 權限 | GitHub OIDC 的短效 Terraform identity |

The Terraform deployer has infrastructure-administration roles. Data loading and dbt builds re-authenticate as the separate runtime service account, which has only BigQuery job execution, dataset editor, and landing-bucket object access. No service-account JSON key is created.

Terraform deployer 擁有基礎設施管理角色；載入資料與 dbt build 會重新驗證成另一個 runtime service account，只有 BigQuery job 執行、指定 dataset 編輯與 landing bucket object 權限。此設計不會建立 service-account JSON key。

## One-time bootstrap / 一次性 bootstrap

Prerequisites: an existing billed GCP project, Terraform, `gcloud`, project-owner-equivalent bootstrap permissions, and a GitHub repository. These commands change cloud resources and may incur small storage/query charges.

前置需求：已啟用計費的 GCP project、Terraform、`gcloud`、相當於 project owner 的 bootstrap 權限，以及 GitHub repository。下列命令會修改雲端資源，可能產生少量儲存或查詢費用。

```powershell
gcloud auth application-default login
Copy-Item infra\terraform\bootstrap\terraform.tfvars.example infra\terraform\bootstrap\terraform.tfvars
# Edit only the copied, git-ignored local values before continuing.
Set-Location infra\terraform\bootstrap
terraform init
terraform plan -out bootstrap.tfplan
terraform apply bootstrap.tfplan
terraform output
```

Review the plan before apply. Preserve `bootstrap/terraform.tfstate` securely; it defines the OIDC trust boundary and is intentionally not used by the routine deployment workflow. The state and plan patterns are ignored by Git.

Apply 前必須檢查 plan。請安全保存 `bootstrap/terraform.tfstate`；它定義 OIDC 信任邊界，日常部署 workflow 不會使用它。State 與 plan 檔已由 Git 忽略。

## GitHub environment / GitHub 環境

Create a protected GitHub environment named `gcp-dev`, require reviewer approval for it, and define these **environment variables** from bootstrap outputs and your chosen names:

建立受保護的 GitHub environment `gcp-dev`、設定 reviewer approval，並依 bootstrap outputs 與你選擇的名稱建立下列 **environment variables**：

| Variable | Example/source |
| --- | --- |
| `GCP_PROJECT_ID` | Existing project ID |
| `GCP_REGION` | `us-west1` |
| `GCP_BIGQUERY_LOCATION` | `US` |
| `GCP_LANDING_BUCKET` | A globally unique new bucket name |
| `GCP_TF_STATE_BUCKET` | `state_bucket_name` output |
| `GCP_WIF_PROVIDER` | `workload_identity_provider` output |
| `GCP_TERRAFORM_SERVICE_ACCOUNT` | `terraform_service_account` output |
| `GCP_DBT_SERVICE_ACCOUNT` | `dbt_service_account` output |

No GitHub secret containing a Google credential is required. The provider condition accepts only the configured repository and `main` branch. GitHub-hosted pull requests cannot apply this infrastructure.

不需要保存 Google credential 的 GitHub secret。Provider condition 只接受設定的 repository 與 `main` branch；GitHub-hosted pull request 無法套用此基礎設施。

## Controlled deployment / 受控部署

Run **GCP BigQuery portfolio deployment** manually from GitHub Actions:

1. Choose `plan` first; this is read-only.
2. Review the Terraform plan and expected development resources.
3. Choose `apply` and enter the exact confirmation `DEPLOY`.
4. The workflow applies the reviewed plan, switches to the least-privilege runtime identity, uploads a checksummed 12-row edge-case fixture, loads Bronze tables, executes the dbt build twice, and uploads non-secret verification evidence for 30 days.

先執行唯讀的 `plan` 並檢查結果；確認後選擇 `apply` 並輸入 `DEPLOY`。Workflow 會套用 plan、切換到最小權限 runtime identity、上傳含 checksum 的 12-row edge-case fixture、載入 Bronze tables、連續執行兩次 dbt build，並保存 30 天的非敏感驗證證據。

The fixture load uses `--replace` on `bronze.raw_statcast` and `metadata.pipeline_ranges`. Point this workflow only at the isolated portfolio development project/datasets—not shared or production data.

Fixture load 會對 `bronze.raw_statcast` 與 `metadata.pipeline_ranges` 使用 `--replace`。此 workflow 只能指向隔離的作品集開發 project／datasets，不可連接共享或 production data。

## Evidence and cost guard / 證據與成本防護

`cloud/scripts/verify_bigquery.py` fails unless the five expected fixture row counts, daily partition, and two clustering fields match. It records dry-run bytes for bounded/unbounded scans plus actual bytes, billed bytes, slot milliseconds, cache status, and client-observed latency. The actual benchmark has a 100 MB maximum-bytes-billed guard.

`cloud/scripts/verify_bigquery.py` 只有在五個 fixture row counts、每日分區與兩個 clustering fields 都相符時才會成功；同時記錄有／無日期篩選的 dry-run bytes，以及實際 bytes、billed bytes、slot milliseconds、cache 狀態與 client-observed latency。實際 benchmark 設有 100 MB maximum-bytes-billed 上限。

Artifact metrics from a tiny fixture prove configuration and execution, not production-scale speed. Use real volume only after defining a budget and updating the count expectations separately.

小型 fixture 的 artifact 可證明設定與執行，但不能代表 production-scale 效能。只有在另行定義預算並調整 count expectations 後，才應使用真實大量資料。
