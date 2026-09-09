# Kiro ChatOps Kit

> **Important:** This is sample code for non-production usage. You should work with your security and legal teams to meet your organizational security, regulatory and compliance requirements before deployment.
>
> This sample is provided as-is under the [MIT-0 license](LICENSE).

Run AI-powered code analysis from Slack. Type `/kiro analyze https://github.com/org/repo explain the auth flow` and get results posted directly in your channel.

## How It Works

```
Slack: /kiro analyze https://github.com/org/repo explain the auth flow
  │
  ▼
API Gateway → Dispatcher Lambda (acknowledges in <3s)
                    │
                    │ async invoke
                    ▼
              Worker Lambda
                1. Clones the repo
                2. Runs kiro-cli AI analysis
                3. Posts results back to Slack
```

## What You Need

| Item | Where to get it |
|------|----------------|
| AWS account | With permissions for Lambda, API Gateway, ECR, Secrets Manager |
| Slack workspace | With permission to create apps |
| GitHub PAT | github.com/settings/tokens — `repo` scope |
| Kiro API key | app.kiro.dev → API Keys (requires Pro/Pro+/Power subscription) |
| Finch | https://runfinch.com (or Docker, substituting `docker` for `finch` below) |
| AWS SAM CLI | `brew install aws-sam-cli` or `pip install aws-sam-cli==1.135.0` |

## Quick Start

```bash
# 1. Set up credentials (see SETUP.md for detailed steps)
# 2. Build and push the Worker container
cd worker
finch vm start
finch build --platform linux/amd64 -t kiro-worker:latest .

# 3. Push to ECR
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1
aws ecr get-login-password --region $AWS_REGION | \
  finch login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
finch tag kiro-worker:latest $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest
finch push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest

# 4. Deploy
cd ..
sam build
sam deploy --guided \
  --stack-name kiro-chatops \
  --parameter-overrides EcrImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/kiro-worker:latest

# 5. Update Slack slash command Request URL with the ApiEndpoint output
```

See **SETUP.md** for the complete walkthrough.

## Files

```
sample-kiro-chatops-slack-integration/
├── README.md           # This file
├── SETUP.md            # Complete step-by-step guide
├── template.yaml       # SAM infrastructure template
├── dispatcher/
│   └── index.py        # Slack request handler
└── worker/
    ├── Dockerfile      # Container with git + kiro-cli + dependencies
    └── index.py        # Clone repo + run analysis + post results
```

## Usage (after deployment)

```
/kiro analyze https://github.com/org/repo explain what this repo does
/kiro review https://github.com/org/repo for security issues
/kiro debug https://github.com/org/repo why the payment tests are failing
/kiro explain https://github.com/org/repo the retry logic in order-processor
/kiro                    ← shows usage help
```

## Cost

Estimated ~$17/month AWS for a team of 10 engineers at ~50 analyses/day, based on AWS pricing as of July 2025:
- Lambda: ~1,500 invocations/month × avg 30s Worker duration (1024 MB) ≈ $12
- API Gateway: ~1,500 requests/month ≈ $1.50
- Secrets Manager: 3 secrets + ~3,000 API calls/month ≈ $2.50
- ECR storage: ~500 MB image ≈ $0.05

Kiro subscription credits are billed separately. Actual costs vary with usage, region, and free-tier eligibility. Estimates derived from [AWS Lambda Pricing](https://aws.amazon.com/lambda/pricing/), [API Gateway Pricing](https://aws.amazon.com/api-gateway/pricing/), [Secrets Manager Pricing](https://aws.amazon.com/secrets-manager/pricing/), and [ECR Pricing](https://aws.amazon.com/ecr/pricing/) pages as of July 2025.

## Important Notes

- Analysis results are AI-generated and non-deterministic. The same command can produce different results across runs.
- Kiro CLI's underlying model may change over time, which can shift the style, structure, and conclusions of responses.
- Treat results as assistive, not authoritative. Verify security or debugging conclusions independently.
- CloudWatch Logs may contain repository content and user prompts. Consider restricting log group access via IAM policies or enabling CloudWatch Logs data protection to mask sensitive data in production deployments.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
