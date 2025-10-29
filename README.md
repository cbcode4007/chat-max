# Chat Max

Chat Max is a lightweight GUI for interacting with GPT chat partners either locally with an API key or through a server endpoint if the user chooses, while preserving the request payload shape so existing servers stay compatible. The prompt is engineered in such a way, with the assistance of another AI extracting preferences to a file based on history, that users should feel some more realism in conversation, having various likes and dislikes be remembered and the ability to fine-tune the personality they are speaking with.

The main program file is `chatmax-v0-4-2.py`.

## Key features

- Personality
	- A `Personality` dialog exposes sliders (friendliness, professionalism, profanity, age, gender, humour, sarcasm, extroversion) that are converted into a system instruction which is appended to the outgoing model messages, allowing users to influence various different aspects of their chat partner's responses.
	- Several built-in presets are included. Save/load custom presets to the `personalities/` folder or `presets.json`.

- Preferences
	- The app can generate concise user preference lines also using AI from recent user messages and merge them into `preferences.json` (a timestamped JSON list). This file is inserted as an additional `system` message for the model to gain context and make users feel uniquely remembered. These can be cleared by the user as well.

- Conversations
	- `history` (short context) is used as information about the chat for the model, `full_history` is an untrimmed log used for saving conversations for later revisiting.
	- Use `Conversation -> Save...` and `Conversation -> Load...` to export/import JSON conversation files in `conversations/`.

- Dual run-modes
	- Local: call OpenAI directly (e.g. `gpt-4o-mini`) using an API key stored in `settings.json`.
	- Server: POST the unchanged JSON payload `{"messages": [...]}` to any configured server endpoint.

- Credential management
	- Single source of truth: `settings.json` will store `use_local_ai` boolean, `openai_api_key`, and `server_endpoint`.
	- In-app editors under `Settings` let you add or delete the API key or server endpoint.
	- On deletion, the app records which credential was removed last and, if both credentials are subsequently missing, will prefer to re-prompt for the most recently deleted credential.
	- On fresh installs (no `settings.json`), the app defaults to prompting for the client API key first as that would probably be the more common option, and the last selected is prompted on future runs due to helping users get back to their chats seamlessly.

- Advanced customization
	- Users can visit the Settings menu and adjust their chat partner's amount of lines remembered in a given conversation, and amount of preferences (in lines, each one is a focused sentence like "The user's favourite colour is purple").
	- They are also given 3 options for which GPT model responds: 4o mini, 5 nano and 5 mini. This is for those who have just a little more funds to spare on their API key, as the 5 models are noticably smarter, yet also slower and more costly as they scale up. Personally, I would recommend GPT 5 nano in chat scenarios like this one as its reasoning effort allows it to more closely tailor its responses to the overall personality it was set up with while not sacrificing as much speed (5 mini can get somewhat hung up on a simple 'hello') and still being very cheap (we are talking about ~1 cent per 30 minutes of back and forth talking).

- Robust persistence and atomic writes
	- Settings and presets are written atomically (write `.tmp` then `os.replace`) and attempt an `fsync`/`chmod` where possible.

## File layout

- `chatmax-v0-4-2.py` — main GUI program (run with `python 'chatmax-v0-4-2.py'`).
- `settings.json` — created next to the script, keys:
	- `use_local_ai` (bool)
	- `openai_api_key` (string)
	- `server_endpoint` (string)
	- `last_credential_deleted` (string — `api_key` or `server_endpoint`)
	- `last_credential_deleted_ts` (integer — timestamp)
	- `ai_history_lines` (integer)
	- `pref_memory_lines` (integer)
	- `ai_model` (string)
- `preferences.json` — JSON list of timestamped preference entries merged from conversation extraction.
- `presets.json` — saved presets and last selection.
- `personalities/` — directory for per-preset JSON files (optional).
- `conversations/` — recommended location for saved conversation JSON files. Program will automatically ask if the user wants to load their last conversation on startup if one is found in this directory.

## Running the app

1. Install Python 3.
2. From the project directory run:

```bash
python 'chatmax-v0-4-2.py'
```

On first run the program will prompt for credentials based on the startup logic:

- If both API key and endpoint are missing and `last_credential_deleted` metadata is present, the app will re-prompt for whichever credential was deleted most recently.
- If both are missing and no metadata exists (fresh install), the app prompts for the client OpenAI API key by default. However, the user can opt to enter a server endpoint during this process instead.

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