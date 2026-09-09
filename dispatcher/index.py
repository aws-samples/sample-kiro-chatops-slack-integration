import json
import os
import hashlib
import hmac
import time
import urllib.parse
import boto3

lambda_client = boto3.client("lambda")

_signing_secret = None


def get_signing_secret():
    global _signing_secret
    if _signing_secret is None:
        secrets_client = boto3.client("secretsmanager")
        response = secrets_client.get_secret_value(
            SecretId="kiro-chatops/slack-signing-secret"
        )
        _signing_secret = response["SecretString"]
    return _signing_secret


def verify_slack_signature(event):
    raw_headers = event.get("headers", {})
    headers = {k.lower(): v for k, v in raw_headers.items()}
    timestamp = headers.get("x-slack-request-timestamp", "")
    signature = headers.get("x-slack-signature", "")
    body = event.get("body", "")

    if not timestamp or not signature:
        return False

    if abs(time.time() - int(timestamp)) > 300:
        return False

    signing_secret = get_signing_secret()
    sig_basestring = f"v0:{timestamp}:{body}"
    my_signature = "v0=" + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(my_signature, signature)


def handler(event, context):
    if not verify_slack_signature(event):
        return {"statusCode": 401, "body": "Invalid signature"}

    body = urllib.parse.parse_qs(event.get("body", ""))
    command_text = body.get("text", [""])[0]
    user_name = body.get("user_name", ["unknown"])[0]
    channel_name = body.get("channel_name", ["unknown"])[0]
    response_url = body.get("response_url", [""])[0]

    if not command_text:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": (
                    "Usage: `/kiro [analyze|review|debug|explain] <repo_url> <description>`\n\n"
                    "Examples:\n"
                    "• `/kiro analyze https://github.com/user/repo explain the auth flow`\n"
                    "• `/kiro review https://github.com/user/repo for security issues`\n"
                    "• `/kiro debug https://github.com/user/repo why tests are failing`"
                ),
            }),
        }

    parts = command_text.split()
    repo_url = ""
    prompt_parts = []
    for part in parts:
        if not repo_url and part.startswith("https://"):
            repo_url = part if part.endswith(".git") else part + ".git"
        else:
            prompt_parts.append(part)
    prompt_text = " ".join(prompt_parts)

    if not repo_url:
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": "Please include a repository URL. Example: `/kiro analyze https://github.com/user/repo explain the code`",
            }),
        }

    lambda_client.invoke(
        FunctionName=os.environ["WORKER_FUNCTION_NAME"],
        InvocationType="Event",
        Payload=json.dumps({
            "repo_url": repo_url,
            "is_private": True,
            "command_text": prompt_text,
            "user_name": user_name,
            "channel_name": channel_name,
            "response_url": response_url,
        }),
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "response_type": "in_channel",
            "text": f":hourglass_flowing_sand: *@{user_name}* requested: `{prompt_text}`\nRepo: {repo_url}\nKiro is working on it...",
        }),
    }
