"""
ChatGPT Conversation Exporter

Exports ChatGPT conversations to Markdown files.

Features:
- Prompts for ChatGPT session cookie value(s) at runtime.
- Exports regular/unorganized chats.
- Optionally exports one ChatGPT Project if you paste a project ID.
- Saves conversations as Markdown files in local folders.
- Uses an iterative message walker to avoid recursion errors on long chats.
- Adds clear diagnostics for 401, 403, HTML responses, and invalid JSON.

Important:
- These are unofficial ChatGPT web app endpoints and may stop working.
- This script does not bypass access controls, SSO, bot checks, or Enterprise restrictions.
- Do not paste session tokens into shared notebooks, GitHub, Slack, docs, or chats.
- If a token is exposed, sign out and back into ChatGPT to invalidate it.

Install:
    python3 -m pip install -r requirements.txt

Run:
    python3 chatgpt_exporter.py
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

BASE_URL = "https://chatgpt.com/backend-api"
SESSION_URL = "https://chatgpt.com/api/auth/session"
OUTPUT_DIR = Path("./chatgpt_export_TEST_FULL")
PAGE_SIZE = 100
REQUEST_DELAY_SECONDS = 0.75
TIMEOUT_SECONDS = 30

# Leave this as None unless you know the exact ChatGPT account/workspace header.
# A wrong value here can cause 403 errors.
WORKSPACE_ID: Optional[str] = None


# -----------------------------------------------------------------------------
# Errors and data classes
# -----------------------------------------------------------------------------

class ExporterError(Exception):
    """Base error for expected exporter failures."""


class AuthError(ExporterError):
    """Authentication/session problem."""


class ForbiddenError(ExporterError):
    """403 from ChatGPT. Usually bot protection, wrong workspace, or policy block."""


@dataclass
class AuthCookies:
    token_0: str
    token_1: str = ""

    def cookie_header(self) -> str:
        """Build the Cookie header for split or unsplit session tokens."""
        if self.token_1:
            return (
                f"__Secure-next-auth.session-token.0={self.token_0}; "
                f"__Secure-next-auth.session-token.1={self.token_1}"
            )
        return f"__Secure-next-auth.session-token={self.token_0}"


@dataclass
class OptionalProject:
    project_id: str
    folder_name: str


# -----------------------------------------------------------------------------
# Prompts and helpers
# -----------------------------------------------------------------------------

def prompt_for_auth_cookies() -> AuthCookies:
    print()
    print("Paste your ChatGPT session cookie value(s).")
    print("Input is hidden while you type/paste.")
    print()
    print("If your browser shows ONE cookie named:")
    print("  __Secure-next-auth.session-token")
    print("Paste its VALUE into the first prompt and leave the second blank.")
    print()
    print("If your browser shows TWO cookies named:")
    print("  __Secure-next-auth.session-token.0")
    print("  __Secure-next-auth.session-token.1")
    print("Paste .0 into the first prompt and .1 into the second.")
    print()

    token_0 = getpass("__Secure-next-auth.session-token or .0: ").strip()
    token_1 = getpass("__Secure-next-auth.session-token.1, if present: ").strip()

    if not token_0:
        raise AuthError("No session token was provided.")

    return AuthCookies(token_0=token_0, token_1=token_1)


def prompt_for_optional_project() -> Optional[OptionalProject]:
    print()
    print("Optional project export")
    print("Paste a ChatGPT Project ID to export that project too, or press Enter to skip.")
    print("Project IDs usually start with: g-p-")
    print("Example URL may contain something like: /g/g-p-abc123.../project")
    print()

    project_id = input("Project ID, or Enter to skip: ").strip()
    if not project_id:
        print("Skipping project export.")
        return None

    folder_name = input("Folder name for this project: ").strip()
    if not folder_name:
        folder_name = project_id

    return OptionalProject(project_id=project_id, folder_name=folder_name)


def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename or folder name."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    name = name.strip(". ")
    return name[:100] or "Untitled"


def parse_timestamp(value: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Parse a timestamp that may be Unix seconds or ISO 8601."""
    if not value:
        return "Unknown"

    try:
        return datetime.fromtimestamp(float(value)).strftime(fmt)
    except (TypeError, ValueError, OSError):
        pass

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.astimezone().strftime(fmt)
    except ValueError:
        return str(value)


def looks_like_html(text: str) -> bool:
    prefix = text.lstrip()[:100].lower()
    return prefix.startswith("<!doctype html") or prefix.startswith("<html")


def print_response_diagnostic(resp: requests.Response, label: str) -> None:
    content_type = resp.headers.get("content-type", "")
    print()
    print(f"--- {label} diagnostic ---")
    print(f"URL: {resp.url}")
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {content_type}")
    print(f"Body preview: {resp.text[:800]!r}")
    print("--- end diagnostic ---")
    print()


def require_json_response(resp: requests.Response, label: str) -> Dict[str, Any]:
    """Validate an HTTP response and parse JSON with useful errors."""
    if resp.status_code == 401:
        print_response_diagnostic(resp, label)
        raise AuthError(
            "Got 401 Unauthorized. Your session token is probably expired or incomplete. "
            "Open ChatGPT in your browser, refresh the page, and copy a fresh cookie."
        )

    if resp.status_code == 403:
        print_response_diagnostic(resp, label)
        raise ForbiddenError(
            "Got 403 Forbidden. This usually means one of the following:\n"
            "- the session cookie is expired, copied incorrectly, or split-cookie chunks are wrong;\n"
            "- a placeholder or wrong WORKSPACE_ID is being sent;\n"
            "- Enterprise SSO/security policy blocks this session outside the browser;\n"
            "- ChatGPT's web app bot/security layer returned an HTML block page.\n\n"
            "Try signing out/back into ChatGPT and copying a fresh cookie. "
            "Also make sure WORKSPACE_ID is still None."
        )

    if resp.status_code < 200 or resp.status_code >= 300:
        print_response_diagnostic(resp, label)
        raise ExporterError(f"{label} failed with HTTP {resp.status_code}.")

    if looks_like_html(resp.text):
        print_response_diagnostic(resp, label)
        raise ExporterError(
            f"{label} returned HTML instead of JSON. "
            "This is usually a security, bot, or SSO page."
        )

    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        print_response_diagnostic(resp, label)
        raise ExporterError(f"{label} did not return valid JSON.") from exc


# -----------------------------------------------------------------------------
# ChatGPT web client
# -----------------------------------------------------------------------------

class ChatGPTWebClient:
    def __init__(self, cookies: AuthCookies, workspace_id: Optional[str] = None):
        self.cookies = cookies
        self.workspace_id = workspace_id
        self.session = requests.Session()
        self.access_token: Optional[str] = None

    def base_headers(self) -> Dict[str, str]:
        headers = {
            "Cookie": self.cookies.cookie_header(),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://chatgpt.com/",
            "Origin": "https://chatgpt.com",
        }

        if self.workspace_id:
            headers["ChatGPT-Account-ID"] = self.workspace_id

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        return headers

    def get_access_token(self) -> str:
        print("Getting access token...")
        resp = self.session.get(
            SESSION_URL,
            headers=self.base_headers(),
            timeout=TIMEOUT_SECONDS,
        )

        data = require_json_response(resp, "Session endpoint")
        token = data.get("accessToken")

        if not token:
            print(f"Session response keys: {list(data.keys())}")
            raise AuthError(
                "The session endpoint responded, but no accessToken was present. "
                "Your account/session may not expose one, or the cookie is not the right session."
            )

        self.access_token = token
        print("Access token obtained.")
        return token

    def get_json(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        label: str = "Request",
    ) -> Dict[str, Any]:
        resp = self.session.get(
            url,
            headers=self.base_headers(),
            params=params,
            timeout=TIMEOUT_SECONDS,
        )
        return require_json_response(resp, label)

    def fetch_regular_conversations(self) -> List[Dict[str, Any]]:
        print()
        print("Fetching regular/unorganized conversations...")

        all_items: List[Dict[str, Any]] = []
        offset = 0

        while True:
            params = {"offset": offset, "limit": PAGE_SIZE, "order": "updated"}
            data = self.get_json(
                f"{BASE_URL}/conversations",
                params=params,
                label=f"Conversations page offset={offset}",
            )

            items = data.get("items", []) or []
            total = data.get("total")

            for item in items:
                item["_folder_name"] = "_Uncategorized"

            all_items.extend(items)
            print(f"Fetched {len(items)} items at offset {offset}; total so far {len(all_items)}")

            if not items:
                break
            if isinstance(total, int) and len(all_items) >= total:
                break

            offset += PAGE_SIZE
            time.sleep(REQUEST_DELAY_SECONDS)

        print(f"Found {len(all_items)} regular/unorganized conversations.")
        return all_items

    def fetch_project_conversations(self, project_id: str, folder_name: str) -> List[Dict[str, Any]]:
        print()
        print(f"Fetching project: {folder_name} ({project_id})")

        # Different ChatGPT environments have exposed project conversations through
        # different endpoint names over time. Try both.
        endpoint_candidates = [
            f"{BASE_URL}/gizmos/{project_id}/conversations",
            f"{BASE_URL}/projects/{project_id}/conversations",
        ]

        last_error: Optional[Exception] = None

        for endpoint_url in endpoint_candidates:
            print(f"Trying endpoint: {endpoint_url}")
            cursor: Optional[str] = None
            endpoint_items: List[Dict[str, Any]] = []

            try:
                while True:
                    params = {"cursor": cursor} if cursor else None
                    data = self.get_json(
                        endpoint_url,
                        params=params,
                        label=f"Project conversations {folder_name}",
                    )

                    items = data.get("items", data.get("conversations", [])) or []

                    for item in items:
                        item["_folder_name"] = folder_name

                    endpoint_items.extend(items)
                    print(f"  fetched {len(items)} project items; total so far {len(endpoint_items)}")

                    cursor = data.get("cursor") or data.get("next_cursor")
                    if not cursor or not items:
                        break

                    time.sleep(REQUEST_DELAY_SECONDS)

                if endpoint_items:
                    print(f"Found {len(endpoint_items)} project conversations using this endpoint.")
                    return endpoint_items

                print("This endpoint returned 0 project conversations.")

            except ForbiddenError:
                raise
            except Exception as exc:
                last_error = exc
                print(f"Could not use this endpoint: {exc}")

        if last_error:
            print(f"No project conversations fetched. Last error was: {last_error}")
        else:
            print("No project conversations fetched from either endpoint.")

        return []

    def fetch_conversation_detail(self, conversation_id: str) -> Dict[str, Any]:
        return self.get_json(
            f"{BASE_URL}/conversation/{conversation_id}",
            label=f"Conversation detail {conversation_id}",
        )


# -----------------------------------------------------------------------------
# Conversation parsing and Markdown output
# -----------------------------------------------------------------------------

def extract_text_from_part(part: Any) -> Optional[str]:
    if isinstance(part, str):
        text = part.strip()
        return text if text else None

    if isinstance(part, dict):
        if part.get("content_type") == "code" and part.get("text"):
            return f"```\n{part['text']}\n```"

        if part.get("text"):
            return str(part["text"])

    return None


def extract_messages(detail: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract messages from the main conversation branch without recursion.

    This avoids "maximum recursion depth exceeded" on long/deep chats.
    """
    mapping = detail.get("mapping", {}) or {}

    if not mapping:
        return []

    root_id: Optional[str] = None

    for node_id, node in mapping.items():
        if node.get("parent") is None:
            root_id = node_id
            break

    if not root_id:
        return []

    messages: List[Dict[str, str]] = []
    current_id: Optional[str] = root_id
    visited = set()

    while current_id:
        if current_id in visited:
            print("Warning: detected a loop in the conversation tree; stopping message walk.")
            break

        visited.add(current_id)

        node = mapping.get(current_id)
        if not node:
            break

        msg = node.get("message")

        if msg:
            role = msg.get("author", {}).get("role", "unknown")
            content_obj = msg.get("content", {}) or {}
            parts = content_obj.get("parts", []) or []

            if role in {"user", "assistant"}:
                text_parts = []

                for part in parts:
                    text = extract_text_from_part(part)
                    if text:
                        text_parts.append(text)

                if text_parts:
                    messages.append(
                        {
                            "role": role,
                            "timestamp": parse_timestamp(msg.get("create_time")) if msg.get("create_time") else "",
                            "content": "\n\n".join(text_parts),
                        }
                    )

        children = node.get("children", []) or []

        # Follow first child as the main branch.
        # This skips alternate regenerated responses.
        current_id = children[0] if children else None

    return messages


def conversation_to_markdown(convo_meta: Dict[str, Any], messages: List[Dict[str, str]]) -> str:
    title = convo_meta.get("title") or "Untitled"
    created_str = parse_timestamp(convo_meta.get("create_time"))
    updated_str = parse_timestamp(convo_meta.get("update_time"))
    conversation_id = convo_meta.get("id", "Unknown")

    lines = [
        f"# {title}",
        "",
        f"**Conversation ID:** {conversation_id}  ",
        f"**Created:** {created_str}  ",
        f"**Last updated:** {updated_str}",
        "",
        "---",
        "",
    ]

    for msg in messages:
        role_label = "You" if msg["role"] == "user" else "ChatGPT"
        ts = f" _{msg['timestamp']}_" if msg.get("timestamp") else ""

        lines.extend(
            [
                f"## {role_label}{ts}",
                "",
                msg["content"],
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines)


def unique_markdown_path(folder: Path, safe_title: str, updated: Any, title_counts: Dict[str, int]) -> Path:
    key = str(folder / safe_title)

    if key not in title_counts:
        title_counts[key] = 1
        return folder / f"{safe_title}.md"

    title_counts[key] += 1
    suffix = parse_timestamp(updated, fmt="%Y%m%d") if updated else str(title_counts[key])
    return folder / f"{safe_title}_{suffix}.md"


# -----------------------------------------------------------------------------
# Export flow
# -----------------------------------------------------------------------------

def export_conversations(client: ChatGPTWebClient, optional_project: Optional[OptionalProject]) -> None:
    client.get_access_token()

    all_convos = client.fetch_regular_conversations()

    if optional_project:
        time.sleep(REQUEST_DELAY_SECONDS)
        project_convos = client.fetch_project_conversations(
            optional_project.project_id,
            optional_project.folder_name,
        )
        all_convos.extend(project_convos)

    # De-duplicate by conversation ID while preserving order.
    seen_ids = set()
    deduped_convos: List[Dict[str, Any]] = []

    for convo in all_convos:
        convo_id = convo.get("id")
        if not convo_id:
            continue
        if convo_id in seen_ids:
            continue

        seen_ids.add(convo_id)
        deduped_convos.append(convo)

    if not deduped_convos:
        print("No conversations found.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print()
    print(f"Exporting to: {OUTPUT_DIR.resolve()}")
    print(f"Processing {len(deduped_convos)} conversations...")
    print()

    title_counts: Dict[str, int] = {}
    saved = 0
    skipped = 0
    errors = 0

    for index, convo in enumerate(deduped_convos, start=1):
        convo_id = convo.get("id")
        title = convo.get("title") or "Untitled"
        safe_title = sanitize_filename(title)
        folder_name = sanitize_filename(str(convo.get("_folder_name") or "_Uncategorized"))
        folder = OUTPUT_DIR / folder_name
        folder.mkdir(parents=True, exist_ok=True)

        filepath = unique_markdown_path(folder, safe_title, convo.get("update_time"), title_counts)

        print(f"[{index}/{len(deduped_convos)}] {title[:80]}")

        if filepath.exists():
            print(f"  Already exists: {filepath.name}")
            skipped += 1
            continue

        try:
            detail = client.fetch_conversation_detail(str(convo_id))
            messages = extract_messages(detail)
            markdown = conversation_to_markdown(convo, messages)
            filepath.write_text(markdown, encoding="utf-8")
            print(f"  Saved: {filepath}")
            saved += 1

        except ForbiddenError:
            raise

        except Exception as exc:
            print(f"  Error exporting {convo_id}: {exc}")
            errors += 1

        time.sleep(REQUEST_DELAY_SECONDS)

    print()
    print("=" * 60)
    print("Export complete")
    print(f"Saved:   {saved}")
    print(f"Skipped: {skipped}")
    print(f"Errors:  {errors}")
    print(f"Output:  {OUTPUT_DIR.resolve()}")
    print("=" * 60)

    print()
    print("Folder summary:")
    folder_counts: Dict[str, int] = {}
    for path in OUTPUT_DIR.rglob("*.md"):
        folder_counts[path.parent.name] = folder_counts.get(path.parent.name, 0) + 1
    for folder_name, count in sorted(folder_counts.items()):
        print(f"  {folder_name}/ ({count} files)")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("ChatGPT Conversation Exporter")
    print("=" * 60)
    print()

    if WORKSPACE_ID and "put your workspace" in WORKSPACE_ID.lower():
        print("WORKSPACE_ID still looks like a placeholder.")
        print("Set it to None or a real ID.")
        return 2

    try:
        cookies = prompt_for_auth_cookies()
        optional_project = prompt_for_optional_project()
        client = ChatGPTWebClient(cookies=cookies, workspace_id=WORKSPACE_ID)
        export_conversations(client, optional_project)
        return 0

    except ForbiddenError as exc:
        print(f"Forbidden: {exc}")
        return 3

    except AuthError as exc:
        print(f"Authentication error: {exc}")
        return 4

    except KeyboardInterrupt:
        print()
        print("Interrupted.")
        return 130

    except Exception as exc:
        print(f"Unexpected error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
