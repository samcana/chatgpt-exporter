# ChatGPT Conversation Exporter

A small local Python script that exports your ChatGPT conversations to Markdown files.

It exports regular/unorganized chats by default. Project export is optional: when the script runs, it asks whether you want to paste a ChatGPT Project ID. If you press Enter, it skips project export.

## What it does

- Prompts for your ChatGPT session cookie at runtime.
- Supports both unsplit and split ChatGPT session cookies:
  - `__Secure-next-auth.session-token`
  - `__Secure-next-auth.session-token.0` and `__Secure-next-auth.session-token.1`
- Exports regular conversations to Markdown.
- Optionally exports one ChatGPT Project if you paste a project ID.
- Saves files into `chatgpt_export/`.
- Saves regular chats under `_Uncategorized/`.
- Saves project chats under the project folder name you provide.
- Uses an iterative conversation-tree walker to avoid `maximum recursion depth exceeded` on long chats.
- Prints helpful diagnostics for common failures like `401`, `403`, HTML responses, expired cookies, or invalid JSON.

## Important warnings

This uses unofficial ChatGPT web app endpoints. They may change or stop working at any time.

This script does **not** bypass access controls, Enterprise SSO policies, bot checks, admin restrictions, or workspace permissions.

Do **not** paste session tokens into GitHub, shared notebooks, Slack, docs, or chats. Treat session cookies like passwords. If a token is exposed, sign out and back into ChatGPT to invalidate it.

For ChatGPT Enterprise or Business workspaces, the official route for full organizational exports may be through your workspace admin or compliance tooling.

## Requirements

- Python 3.9+
- `requests`

## Install

```bash
python3 -m pip install -r requirements.txt
```

On Windows, you may need:

```bash
py -m pip install -r requirements.txt
```

## Run

```bash
python3 chatgpt_exporter.py
```

On Windows:

```bash
py chatgpt_exporter.py
```

## Using Thonny

1. Install Thonny.
2. Open `chatgpt_exporter.py`.
3. Go to **Tools -> Manage packages**.
4. Install `requests`.
5. Press the green **Run** button.

## Getting your ChatGPT session cookie

In Chrome:

1. Open ChatGPT and make sure you are logged in.
2. Right-click the page and choose **Inspect**.
3. Open the **Application** tab.
4. In the left sidebar, open **Cookies**.
5. Click `https://chatgpt.com`.
6. Find either:
   - `__Secure-next-auth.session-token`, or
   - `__Secure-next-auth.session-token.0` and `__Secure-next-auth.session-token.1`.
7. Copy the **Value**, not the cookie name.

When the script asks:

```text
__Secure-next-auth.session-token or .0:
__Secure-next-auth.session-token.1, if present:
```

If you have one cookie, paste its value into the first prompt and leave the second blank.

If you have two split cookies, paste `.0` into the first prompt and `.1` into the second prompt.

## Optional project export

After the token prompts, the script asks:

```text
Project ID, or Enter to skip:
Folder name for this project:
```

To skip Projects, press Enter at the project ID prompt.

To export a Project, open the Project in ChatGPT and copy the ID from the URL. It usually starts with `g-p-`.

Example:

```text
g-p-69f8b656cc488191b8cb9b5397253ed2
```

Then enter a folder name such as:

```text
Outbound & FINAL Project
```

The script tries both known project endpoint patterns:

- `/backend-api/gizmos/{project_id}/conversations`
- `/backend-api/projects/{project_id}/conversations`

## Output

The script creates a folder called:

```text
chatgpt_export/
```

Regular conversations go here:

```text
chatgpt_export/_Uncategorized/
```

Project conversations go here:

```text
chatgpt_export/<your project folder name>/
```

Each chat is saved as a `.md` file.

## Common errors

### 403 Forbidden

This usually means one of the following:

- The session cookie is expired or copied incorrectly.
- The split cookie chunks were pasted incorrectly.
- Enterprise SSO/security policy blocks this kind of non-browser access.
- ChatGPT's web security layer returned an HTML block page.
- A wrong `WORKSPACE_ID` was set in the script.

Recommended fix:

1. Sign out and back into ChatGPT.
2. Copy a fresh cookie.
3. Make sure `WORKSPACE_ID` is still `None`.
4. Run locally, not in Colab.

### 401 Unauthorized

Your cookie is probably expired, incomplete, or not the right cookie.

### HTML instead of JSON

The endpoint returned a browser/security/SSO page instead of API JSON. This is usually an access or security-layer issue.

### maximum recursion depth exceeded

This version avoids that by walking the conversation tree iteratively.

## GitHub safety checklist

Before pushing to GitHub:

- Do not commit exported chats unless you intentionally want them public/private in that repo.
- Do not commit cookies, tokens, `.env` files, or logs containing secrets.
- Keep `chatgpt_export/` ignored.
- Keep any zip exports ignored.

This repository includes a `.gitignore` for those files.
