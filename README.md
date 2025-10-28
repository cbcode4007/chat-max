# Chat Max

Chat Max is a lightweight GUI for interacting with personalized GPT chat partners either locally with an API key or through a server endpoint if the user chooses, while preserving the request payload shape so existing servers stay compatible.

The main program file is `chatmax-v0-4-2.py`.

## Key features

- Dual run-modes
	- Local: call OpenAI directly (e.g. `gpt-4o-mini`) using an API key stored in `settings.json`.
	- Server: POST the unchanged JSON payload `{"messages": [...]}` to any configured server endpoint.

- Credential management
	- Single source of truth: `settings.json` will store `use_local_ai` boolean, `openai_api_key`, and `server_endpoint`.
	- In-app editors under `Settings` let you add or delete the API key or server endpoint.
	- On deletion, the app records which credential was removed last and, if both credentials are subsequently missing, will prefer to re-prompt for the most recently deleted credential.
	- On fresh installs (no `settings.json`), the app defaults to prompting for the client API key first as that would probably be the more common option, and the last selected is prompted on future runs due to helping users get back to their chats seamlessly.

- Personality mixer and presets
	- A `Personality` dialog exposes sliders (friendliness, professionalism, profanity, age, gender, humour, sarcasm, extroversion) that are converted into a system instruction which is appended to the outgoing model messages, allowing users to influence various different aspects of their chat partner's responses.
	- Several built-in presets are included. Save/load custom presets to the `personalities/` folder or `presets.json`.

- Preference extraction
	- The app can extract concise user preference lines from recent user messages and merge them into `preferences.json` (a timestamped JSON list). This file is inserted as an additional `system` message for the model to gain context and make users feel uniquely remembered.

- Robust persistence and atomic writes
	- Settings and presets are written atomically (write `.tmp` then `os.replace`) and attempt an `fsync`/`chmod` where possible.

- Conversation saving and history
	- `history` (short context) is used as the model context; `full_history` is an untrimmed log used for saving conversations.
	- Use `Conversation -> Save...` and `Conversation -> Load...` to export/import JSON conversation files in `conversations/`.

- Advanced customization
	- Users can visit the Settings menu and adjust their chat partner's amount of lines remembered in a given conversation, and amount of preferences (in lines, each one is a focused sentence like "The user's favourite colour is purple").

## File layout

- `chatmax-v0-4-2.py` — main GUI program (run with `python 'chatmax-v0-4-2.py'`).
- `settings.json` — created next to the script; keys:
	- `use_local_ai` (bool)
	- `openai_api_key` (string)
	- `server_endpoint` (string)
	- `last_credential_deleted` (string — `api_key` or `server_endpoint`)
- `preferences.json` — JSON list of timestamped preference entries merged from conversation extraction.
- `presets.json` — saved presets and last selection.
- `personalities/` — directory for per-preset JSON files (optional).
- `conversations/` — recommended location for saved conversation JSON files. Program will automatically ask if the user wants to load their last conversation if one is found in this directory.

## Running the app

1. Install Python 3.
2. From the project directory run:

```bash
python 'chatmax-v0-4-2.py'
```

On first run the program will prompt for credentials based on the startup logic:

- If both API key and endpoint are missing and `last_credential_deleted` metadata is present, the app will re-prompt for whichever credential was deleted most recently.
- If both are missing and no metadata exists (fresh install), the app prompts for the client OpenAI API key by default.

## Settings and UX notes

- Toggle local vs server: `Settings -> Use local OpenAI (gpt-4o-mini)` — the app will persist this choice to `settings.json`.
- Editing credentials: `Settings -> API Key...` and `Settings -> Server endpoint...` — each dialog lets you save/paste/delete values.
- Deleting a credential: the app persists which credential was deleted most recently (so if both end up missing it will re-prompt for the one you removed last).

Security note: the API key is stored in `settings.json` in plaintext. May be updated later.

## Developer notes

- Calls to OpenAI are made in a background thread to keep the UI responsive. The UI inserts an assistant placeholder while waiting for the reply.
- `call_local_openai()` and `call_server_api()` centralize the two call paths.
- Preference extraction is routed through the same call routing (local vs server) so the extractor behaves the same way the main chat does.

## Troubleshooting

- If dialogs fail to appear on startup, ensure you're running the latest script version (dialogs are scheduled after UI creation to avoid Tcl errors).
- If the app seems to ignore `settings.json`, check file permissions and confirm the file content or remove it to force a fresh startup prompt.

## Planned Improvements

- User selection of AI models for the local call mode.
- A change of the credential prompts that lets the user switch modes before getting into one, so they can back out or enter desired credential.