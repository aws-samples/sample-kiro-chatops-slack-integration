# Setup Guide

Complete step-by-step instructions to deploy Kiro ChatOps from scratch.

---

## Step 1: Gather Credentials

You need four credentials before starting. Collect them all first, then store them in AWS.

### 1A. GitHub Personal Access Token

This allows the Worker to clone private repositories.

1. Go to https://github.com/settings/tokens
2. Click **Generate new token** → **Generate new token (classic)**
3. Settings:
   - Note: `kiro-chatops`
   - Expiration: 30 days
   - Scopes: check **`repo`**
4. Click **Generate token**
5. Copy the token (starts with `ghp_`) — it won't be shown again

### 1B. Kiro API Key

This authenticates the AI analysis engine. Requires a Kiro Pro, Pro+, or Power subscription.

1. Go to https://app.kiro.dev and sign in
2. Navigate to **API Keys**
3. Click **Create new API key**
4. Name: `kiro-chatops`
5. Copy the key (starts with `ksk_`) — only shown once

### 1C. Create the Slack App

1. Go to https://api.slack.com/apps → **Create New App** → **From scratch**
2. App Name: `Kiro Agent`, select your workspace
3. On the **Basic Information** page, scroll to **App Credentials**
4. Copy the **Signing Secret** (32-character hex string)

### 1D. Configure Slash Command

1. In your Slack App settings → **Slash Commands** → **Create New Command**
2. Fill in:
   - Command: `/kiro`
   - Request URL: `https://placeholder` (you'll update this in Step 5)
   - Short Description: `Run Kiro-CLI development tasks`
   - Usage Hint: `[analyze|review|debug|explain] <repo_url> <description>`
3. Save

### 1E. Install the App

1. Go to **OAuth & Permissions** → add Bot Token Scope: `commands`
2. Click **Install to Workspace** → Authorize

> **Note:** No bot token is needed. The Worker posts results to the `response_url`
> from the slash command payload, which is a pre-authenticated webhook. Add
> `chat:write` and store the bot token only if you extend this to post messages
> outside a slash command response.

---

## Step 2: Store Secrets in AWS

```bash
aws secretsmanager create-secret \
  --name kiro-chatops/slack-signing-secret \
  --secret-string "<your-signing-secret-from-step-1C>" \
  --region us-east-1

aws secretsmanager create-secret \
  --name kiro-chatops/git-token \
  --secret-string "<your-github-pat-from-step-1A>" \
  --region us-east-1

aws secretsmanager create-secret \
  --name kiro-chatops/kiro-api-key \
  --secret-string "<your-kiro-key-from-step-1B>" \
  --region us-east-1
```

Verify they were created:

```bash
aws secretsmanager list-secrets \
  --filter Key="name",Values="kiro-chatops" \
  --query "SecretList[].Name" \
  --output table \
  --region us-east-1
```

---

## Step 3: Build and Push the Worker Container

### Prerequisites

- Finch installed and running:
  ```bash
  # Install Finch from https://runfinch.com
  finch vm init            # First time only (requires sudo)
  finch vm start
  ```

### Build

**Important:** Build for `linux/amd64` — Lambda runs x86_64 by default.

```bash
cd worker
finch build --platform linux/amd64 -t kiro-worker:latest .
```

### Push to ECR

```bash
# Set variables
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

# Create repository (first time only)
aws ecr create-repository --repository-name kiro-worker --region $AWS_REGION

# Login
aws ecr get-login-password --region $AWS_REGION | \
  finch login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Tag and push
finch tag kiro-worker:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest
finch push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest
```

---

## Step 4: Deploy with SAM

```bash
cd ..   # Back to the kit root (where template.yaml is)

sam build

sam deploy --guided \
  --stack-name kiro-chatops \
  --parameter-overrides EcrImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest
```

SAM will prompt:
- Stack name: `kiro-chatops`
- Region: `us-east-1`
- Confirm changes: **Y**
- Allow SAM to create IAM roles: **Y**
- DispatcherFunction has no authentication. Is this okay? **Y** (auth is handled in code via Slack signing secret)

After deploy completes, note the **ApiEndpoint** output:
```
https://xxxxxxxx.execute-api.us-east-1.amazonaws.com/Prod/slack/command
```

---

## Step 5: Connect Slack to the Endpoint

1. Go to https://api.slack.com/apps → select **Kiro Agent**
2. Go to **Slash Commands** → edit `/kiro`
3. Replace the Request URL with the **ApiEndpoint** from Step 4
4. Save

---

## Step 6: Test

In any Slack channel where the app is installed:

```
/kiro analyze https://github.com/your-org/your-repo explain what this repo does
```

**Expected behavior:**
1. Immediately: "⏳ @you requested: `explain what this repo does` — Kiro is working on it..."
2. After 15-60 seconds: Analysis results appear in the channel

**Other test commands:**
```
/kiro review https://github.com/org/repo for security issues
/kiro explain https://github.com/org/repo the authentication logic
/kiro debug https://github.com/org/repo why tests are failing
/kiro        ← shows usage help
```

---

## Updating the Worker

After modifying `worker/index.py` or `worker/Dockerfile`:

```bash
cd worker
finch build --platform linux/amd64 -t kiro-worker:latest .
finch tag kiro-worker:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest
finch push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest

aws lambda update-function-code \
  --function-name <WorkerFunctionName-from-SAM-output> \
  --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest \
  --region us-east-1
```

Wait ~20 seconds for the update to propagate, then test.

---

## Cleanup

Remove everything when done testing:

```bash
# Delete the stack
sam delete --stack-name kiro-chatops

# Delete ECR repository
aws ecr delete-repository --repository-name kiro-worker --force --region us-east-1

# Delete secrets
aws secretsmanager delete-secret --secret-id kiro-chatops/slack-signing-secret --force-delete-without-recovery --region us-east-1
aws secretsmanager delete-secret --secret-id kiro-chatops/git-token --force-delete-without-recovery --region us-east-1
aws secretsmanager delete-secret --secret-id kiro-chatops/kiro-api-key --force-delete-without-recovery --region us-east-1

# Delete Slack App: api.slack.com/apps → select app → Delete App
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "app did not respond" in Slack | Dispatcher Lambda crashing | Check CloudWatch logs for the Dispatcher function |
| `Runtime.ImportModuleError` | Handler path mismatch | Ensure handler is `index.handler` in Lambda config |
| `Runtime.InvalidEntrypoint` | Image architecture mismatch | Rebuild with `--platform linux/amd64` and re-push |
| "Permission denied: kiro-cli" | Lambda user can't access `/root/` | kiro-cli must be in `/usr/local/bin/` (Dockerfile handles this) |
| "Read-only file system" | kiro-cli can't write state | `HOME=/tmp` is set in worker code (already handled) |
| "cannot open shared object file" | Missing system library | Add the library to `dnf install` in Dockerfile |
| "Invalid signature" | Wrong signing secret | Verify `kiro-chatops/slack-signing-secret` matches Slack App settings |
| "git clone failed: 403" | Token expired or wrong scope | Regenerate GitHub PAT with `repo` scope, update secret |
| No response after "working on it" | Worker failed silently | Check Worker CloudWatch logs |
| Response takes >60 seconds | Large repo or complex prompt | Normal for big repos; try a more specific prompt |

### Checking Logs

```bash
# Dispatcher logs
aws logs tail /aws/lambda/<DispatcherFunctionName> --follow --region us-east-1

# Worker logs
aws logs tail /aws/lambda/<WorkerFunctionName> --follow --region us-east-1
```

---

## Architecture Notes

- **Why two Lambdas?** Slack requires a response within 3 seconds. Kiro analysis takes 15-60s. The Dispatcher acknowledges instantly; the Worker runs async.
- **Why a container image?** Lambda's default Python runtime doesn't include `git` or `kiro-cli`. A container lets us install everything.
- **Why `--platform linux/amd64`?** Lambda defaults to x86_64. Building on Apple Silicon produces arm64 images that won't run.
- **Why `HOME=/tmp`?** Lambda's filesystem is read-only except `/tmp`. kiro-cli needs to write a session database.
- **Why `/usr/local/bin`?** Lambda runs as an unprivileged user (`sbx_user1051`) that can't access `/root/.local/bin/`.
