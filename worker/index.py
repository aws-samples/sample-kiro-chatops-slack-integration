import json
import os
import re
import subprocess
import shutil
import urllib.request
from urllib.parse import urlparse
import boto3

CLONE_DIR = "/tmp/repo"
# Slack Block Kit allows 3000 chars per section text object. Truncate below
# that so the header and the "truncated" note still fit.
SLACK_BLOCK_TEXT_LIMIT = 3000
MAX_TEXT_CHARS = 2900
# Kiro CLI subprocess limit. Kept under the Lambda 600s timeout so there is
# time left to handle the error and POST back to Slack.
KIRO_TIMEOUT_SECONDS = 540
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
CODE_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
MD_BOLD = re.compile(r"\*\*(.+?)\*\*")
MD_BOLD_ALT = re.compile(r"__(.+?)__")
MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
MD_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")

secrets_client = boto3.client("secretsmanager")


def get_secret(secret_id):
    response = secrets_client.get_secret_value(SecretId=secret_id)
    return response["SecretString"]


def markdown_to_slack(text):
    """Convert standard markdown to Slack mrkdwn format."""
    text = MD_BOLD.sub(r"*\1*", text)
    text = MD_BOLD_ALT.sub(r"*\1*", text)
    text = MD_LINK.sub(r"<\2|\1>", text)
    text = MD_HEADING.sub(r"*\2*", text)
    return text


def split_into_segments(text):
    """Split Kiro output into code blocks and prose segments."""
    segments = []
    last_end = 0

    for match in CODE_FENCE.finditer(text):
        if match.start() > last_end:
            prose = text[last_end:match.start()].strip()
            if prose:
                segments.append(("text", prose))
        lang = match.group(1) or ""
        code = match.group(2).strip()
        segments.append(("code", code, lang))
        last_end = match.end()

    if last_end < len(text):
        prose = text[last_end:].strip()
        if prose:
            segments.append(("text", prose))

    return segments


def build_blocks(header_text, segments):
    """Build Slack Block Kit blocks from parsed segments."""
    blocks = []

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": header_text},
    })
    blocks.append({"type": "divider"})

    for segment in segments:
        if len(blocks) >= 48:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "_... output truncated (50 block limit). Full results in CloudWatch Logs._"},
            })
            break

        if segment[0] == "text":
            converted = markdown_to_slack(segment[1])
            # Slack section text max is 3000 chars; split if needed
            while converted:
                chunk = converted[:MAX_TEXT_CHARS]
                converted = converted[MAX_TEXT_CHARS:]
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": chunk},
                })
        elif segment[0] == "code":
            code_content = segment[1]
            # Wrap in backticks for Slack code block rendering
            formatted = f"```{code_content}```"
            if len(formatted) > SLACK_BLOCK_TEXT_LIMIT:
                formatted = f"```{code_content[:MAX_TEXT_CHARS]}```\n_... code truncated_"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": formatted},
            })

    return blocks


ALLOWED_SLACK_HOSTS = {"hooks.slack.com"}


def post_to_slack(response_url, text, blocks=None):
    parsed = urlparse(response_url)
    if parsed.scheme != "https":
        raise ValueError(f"Refusing to open URL with scheme: {parsed.scheme}")
    if parsed.hostname not in ALLOWED_SLACK_HOSTS:
        raise ValueError(f"Refusing to POST to non-Slack host: {parsed.hostname}")

    payload = {"response_type": "in_channel", "text": text}
    if blocks:
        payload["blocks"] = blocks

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        response_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req)


def cleanup_clone():
    """Remove the cloned repo from /tmp.

    Lambda reuses warm execution environments, so /tmp persists between
    invocations. Clearing it prevents one user's repository from leaking
    into a later invocation.
    """
    if os.path.exists(CLONE_DIR):
        shutil.rmtree(CLONE_DIR, ignore_errors=True)


def clone_repo(repo_url, is_private=False):
    cleanup_clone()

    if is_private:
        token = get_secret("kiro-chatops/git-token")
        repo_url = repo_url.replace("https://", f"https://x-access-token:{token}@")

    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, CLONE_DIR],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        print(f"[git clone error] {result.stderr}")
        raise RuntimeError("git clone failed. Check CloudWatch logs for details.")

    return CLONE_DIR


def run_kiro_analysis(clone_path, command_text):
    kiro_api_key = get_secret("kiro-chatops/kiro-api-key")

    env = os.environ.copy()
    env["KIRO_API_KEY"] = kiro_api_key
    env["HOME"] = "/tmp"

    result = subprocess.run(
        ["kiro-cli", "chat", "--no-interactive", command_text],
        capture_output=True,
        text=True,
        timeout=KIRO_TIMEOUT_SECONDS,
        cwd=clone_path,
        env=env,
    )

    if result.returncode != 0:
        print(f"[kiro-cli error] exit_code={result.returncode}")
        raise RuntimeError("kiro-cli analysis failed. Check CloudWatch logs for details.")

    output = result.stdout.strip()
    return ANSI_ESCAPE.sub("", output)


def handler(event, context):
    command_text = event.get("command_text", "")
    repo_url = event.get("repo_url", "")
    is_private = event.get("is_private", True)
    user_name = event.get("user_name", "unknown")
    response_url = event.get("response_url", "")

    try:
        clone_path = clone_repo(repo_url, is_private)
        analysis = run_kiro_analysis(clone_path, command_text)

        header = f":white_check_mark: *Results for @{user_name}*: `{command_text}`"
        fallback = f"{header}\n\n{analysis}"
        # Slack Block Kit caps section text at 3000 chars; stay under it.
        if len(fallback) > MAX_TEXT_CHARS:
            fallback = fallback[:MAX_TEXT_CHARS] + "\n\n... _(truncated)_"

        segments = split_into_segments(analysis)
        blocks = build_blocks(header, segments)

        post_to_slack(response_url, fallback, blocks=blocks)

    except subprocess.TimeoutExpired:
        minutes = KIRO_TIMEOUT_SECONDS // 60
        post_to_slack(
            response_url,
            f":alarm_clock: *Timeout for @{user_name}*: `{command_text}`\n\nThe analysis took longer than {minutes} minutes. Try a more specific prompt.",
        )
    except Exception as e:
        post_to_slack(
            response_url,
            f":x: *Error for @{user_name}*: `{command_text}`\n\n`{str(e)}`",
        )
    finally:
        cleanup_clone()
