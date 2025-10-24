# File:        chatmax-v0-4-0.py
# Author:      Colin Fajardo
# Version:     0.4 (2025-10-24, user configurable short term memory and preference entry limit)
#
# Description: A simple chat interface for configuring and interacting with 
#              personalized, learning GPT models.

import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
import requests
import json
import threading
import time
import os

# Preferences file path and limits
# Migrate from plain text `preferences.txt` to `preferences.json` which stores
# a list of preference entries with timestamps
# PREFS_MAX_CHARS keeps an optional cap on the total concatenated characters for compatibility
PREFS_PATH = os.path.join(os.path.dirname(__file__), 'preferences.json')
PREFS_MAX_CHARS = 2000
# Default maximum preference entries to keep (can be changed by user via UI)
PREFS_DEFAULT_LINES = 20

def load_prefs_list():
    """Load preference entries from PREFS_PATH.

    Returns a list of dicts: [{'line': str, 'ts': int}, ...] ordered oldest->newest.
    Supports legacy plain-text files by migrating on read.
    """
    try:
        if not os.path.exists(PREFS_PATH):
            # Try to read legacy preferences.txt and migrate
            legacy_txt = os.path.join(os.path.dirname(__file__), 'preferences.txt')
            if os.path.exists(legacy_txt):
                try:
                    with open(legacy_txt, 'r', encoding='utf-8') as f:
                        txt = f.read().strip()
                    lines = [l.strip() for l in txt.splitlines() if l.strip()]
                    out = []
                    for l in lines:
                        out.append({'line': l, 'ts': int(time.time())})
                    # write migrated file
                    _atomic_write(PREFS_PATH, json.dumps(out, ensure_ascii=False, indent=2))
                    try:
                        os.remove(legacy_txt)
                    except Exception:
                        pass
                    return out
                except Exception:
                    return []
            return []
        with open(PREFS_PATH, 'r', encoding='utf-8') as pf:
            loaded = json.load(pf)
        out = []
        if isinstance(loaded, list):
            for item in loaded:
                if isinstance(item, dict) and 'line' in item:
                    try:
                        ts = int(item.get('ts')) if item.get('ts') is not None else int(time.time())
                    except Exception:
                        ts = int(time.time())
                    out.append({'line': str(item.get('line') or ''), 'ts': ts})
                else:
                    # older formats where each list item is a string
                    out.append({'line': str(item), 'ts': int(time.time())})
        elif isinstance(loaded, str):
            for l in loaded.splitlines():
                l = l.strip()
                if l:
                    out.append({'line': l, 'ts': int(time.time())})
        return out
    except Exception:
        return []


def save_prefs_list(entries: list):
    """Persist preference entries (list of {'line', 'ts'}) atomically."""
    try:
        # Ensure serializable
        serial = []
        for e in entries:
            serial.append({'line': str(e.get('line') or ''), 'ts': int(e.get('ts') or int(time.time()))})
        _atomic_write(PREFS_PATH, json.dumps(serial, ensure_ascii=False, indent=2))
    except Exception:
        pass

# OpenAI API key storage (prompt at startup if not present)
OPENAI_API_KEY = None
SETTINGS_PATH = os.path.join(os.path.dirname(__file__), 'settings.json')

# endpoint = 'http://192.168.123.128:5001/chat'
endpoint = ''

# Built-in presets (shared so they can be referenced at startup)
DEFAULT_PRESETS = {
    'Default AI': (2, 1, 0, 30, 1, 0, 0, 1),
    'Helpful Professional': (2, 2, 0, 35, 1, 0, 0, 1),
    'Casual Friendly': (3, 0, 0, 25, 1, 1, 0, 1),
    'Playful Sarcastic': (2, 0, 1, 18, 1, 2, 2, 1),
    'Child-Friendly': (3, 1, 0, 12, 1, 0, 0, 2),
    'Stoic Professional': (1, 2, 0, 40, 1, 0, 0, 0),
    'Sailor-Mouth': (0, 0, 2, 30, 1, 1, 2, 0),
}


def _trim_history():
    """Trim the in-memory short-term history according to HISTORY_LIMIT.

    Centralized helper so callers can request trimming without repeating
    defensive checks. HISTORY_LIMIT is clamped at startup; if missing we
    fall back to the legacy default of 10.
    """
    try:
        _limit = globals().get('HISTORY_LIMIT', None)
        if isinstance(_limit, int):
            while len(history) > _limit:
                history.pop(0)
        else:
            while len(history) > 10:
                history.pop(0)
    except Exception:
        try:
            while len(history) > 10:
                history.pop(0)
        except Exception:
            pass

def send_message():
    message = entry.get()
    if not message.strip():
        return

    # Add to history (keep last 10 messages), each entry is (role, message, iso_timestamp)
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    history.append(("You", message, ts))
    # Also append to the untrimmed full_history for persistence
    full_history.append(("You", message, ts))
    try:
        _trim_history()
    except Exception:
        pass

    # Determine the active preset label (use in UI instead of generic 'AI')
    try:
        preset_label = determine_active_preset_name()
    except Exception:
        preset_label = 'AI'

    # Convert GUI history to ChatGPT format under system role
    # Start with a neutral, blank-slate system instruction, all tone/style should be provided
    # by subsequent system messages (e.g., personality_instruction and preferences)
    messages_for_gpt = [{"role": "system", "content": (
        f"Your name is {preset_label} and you are a user's chat partner. As such, you should keep responses concise, try to adapt them based on the context of the conversation, and for the most part the user's preferences or tone depending on your personality defined below."
    )}]

    # Personality instructions built from sliders (appended as another system message)
    def build_personality_instructions():
        parts = []
        # core sliders
        f = friendliness_var.get()
        p = professionalism_var.get()
        r = profanity_var.get()
        a = age_var.get()
        g = gender_var.get()
        h = humor_var.get()
        s = sarcasm_var.get()
        i = introversion_var.get()

        # Friendliness (0-3)
        if f == 3:
            parts.append('Be very friendly and warm.')
        elif f == 2:
            parts.append('Be friendly.')
        elif f == 1:
            parts.append('Be slightly reserved.')
        else:
            parts.append('Be very reserved and blunt.')

        # Professionalism (0-2)
        if p == 2:
            parts.append('Maintain a professional tone.')
        elif p == 1:
            parts.append('Be somewhat professional.')
        else:
            parts.append('Use casual language.')

        # Profanity (0-2), but enforce age constraint, young voices should not use profanity
        if a <= 15:
            # force no profanity for young ages regardless of setting
            parts.append('Do not use profanity under any circumstances; avoid coarse language due to youthful voice.')
        else:
            if r == 2:
                parts.append('Profanity allowed: high (use strong coarse language as much as possible if it makes sense).')
            elif r == 1:
                parts.append('Profanity allowed: moderate (may use mild swear words).')
            else:
                parts.append('No profanity; use clean language.')

        # Age (5-127)
        parts.append(f'Adopt the voice of someone aged {a}.')

        # Gender (0-2)
        if g == 2:
            parts.append('Use a feminine voice/wording.')
        elif g == 0:
            parts.append('Use a masculine voice/wording.')
        else:
            parts.append('Use neutral wording.')

        # Humor (0-2)
        if h == 2:
            parts.append('Use high levels of humour where appropriate.')
        elif h == 1:
            parts.append('Use light humour occasionally.')
        else:
            parts.append('Avoid humour; be straightforward.')

        # Sarcasm (0-2)
        if s == 2:
            parts.append('Sarcasm permitted: use sharp, ironic remarks when fitting.')
        elif s == 1:
            parts.append('Sarcasm permitted: mild, playful irony allowed.')
        else:
            parts.append('Do not use sarcasm; be literal and sincere.')

        # Extroversion (0-2)
            if i == 2:
                parts.append('Favor social/outgoing hobbies and confident wording. Be excitable and enthusiastic where appropriate, expressing with exclamation marks more often than not.')
            elif i == 1:
                parts.append('No particular bias toward extroversion or introversion.')
            else:
                parts.append("Favor solitary/quiet hobbies and mention mild nervousness or reserve in social situations when relevant. Do not be excitable, for instance lay off of exclamation marks unless absolutely necessary.")

        return ' '.join(parts)

    personality_instruction = build_personality_instructions()
    if personality_instruction:
        messages_for_gpt.append({"role": "system", "content": personality_instruction})

    # If a preferences.txt file exists next to this script, append its contents as an additional system message
    try:
        import os
        prefs_path = os.path.join(os.path.dirname(__file__), 'preferences.txt')
        if os.path.exists(prefs_path):
            with open(prefs_path, 'r', encoding='utf-8') as pf:
                prefs_text = pf.read().strip()
                if prefs_text:
                    messages_for_gpt.append({"role": "system", "content": prefs_text})
        else:
            # Create an empty preferences.txt file
            with open(prefs_path, 'w', encoding='utf-8') as pf:
                pf.write('')
    except Exception:
        # Ignore preference-load errors, do not change payload if this reading fails
        pass
    # Add each entry under short term history to the payload
    for entry_item in history:
        if len(entry_item) >= 2:
            role = entry_item[0]
            msg = entry_item[1]
            messages_for_gpt.append({"role": "user" if role == "You" else "assistant", "content": msg})

    # Ensure the current user message is present in the payload even when
    # the in-memory short-term history limit is set to 0 (which would
    # otherwise remove recently-appended items)
    # Avoid duplicating if it's already present
    try:
        if not any(m.get('role') == 'user' and m.get('content') == message for m in messages_for_gpt):
            messages_for_gpt.append({"role": "user", "content": message})
    except Exception:
        try:
            messages_for_gpt.append({"role": "user", "content": message})
        except Exception:
            pass

    # Add user message to chat UI immediately (include timestamp if enabled) and insert AI placeholder
    try:
        # Insert the user's message immediately with colored label
        insert_labeled_message('You', message, ts)
    except Exception:
        try:
            if show_timestamps_var.get():
                append_chat(f"You [{ts}]: {message}\n\n")
            else:
                append_chat(f"You: {message}\n\n")
        except Exception:
            append_chat(f"You [{ts}]: {message}\n\n")
    try:
        # Insert assistant placeholder with colored preset label (no colon)
        insert_labeled_message(preset_label, 'is thinking...', prefix_colon=False)
    except Exception:
        append_chat(f"{preset_label} is thinking...\n\n")
    entry.delete(0, tk.END)
    chat_area.see(tk.END)

    # Disable send controls while awaiting a reply
    send_btn.config(state=tk.DISABLED)
    entry.config(state=tk.DISABLED)
    try:
        show_ts_cb.config(state=tk.DISABLED)
    except Exception:
        pass
    # Mark as having unsaved changes (a new outgoing message)
    try:
        global unsaved_changes
        unsaved_changes = True
    except Exception:
        pass

    def worker(payload):
        try:            
            # Attempt to extract new/updated preferences from recent conversation and merge into PREFS_PATH
            try:
                # Load current prefs (may be empty)
                current_prefs = ''                
                if os.path.exists(PREFS_PATH):
                    try:
                        with open(PREFS_PATH, 'r', encoding='utf-8') as pf:
                            current_prefs = pf.read().strip()
                    except Exception:
                        current_prefs = ''

                # Build a prompt to extract concise preference lines, from the user's messages only
                gen_msgs = [
                    {"role": "system", "content": (
                        "Extract concise user preference statements from the conversation. "
                        "Important: consider ONLY the user's messages; ignore all assistant/AI utterances. "
                        "Output plain text only, one canonical statement per line, using this exact pattern: The user's <property> is <value>. "
                        "Examples: The user's favourite colour is purple; The user's name is Colin. "
                        "Do NOT include numbering, explanations, or extra commentary. Compare with the existing preferences below and output ONLY NEW or UPDATED preference lines (one per line). If there are none, output nothing."
                    )},
                ]

                # Include existing preferences (migrate/load JSON) as context
                try:
                    existing_prefs_list = load_prefs_list()
                    if existing_prefs_list:
                        prefs_text = '\n'.join([p.get('line','') for p in existing_prefs_list])
                        gen_msgs.append({"role": "system", "content": "Existing preferences:\n" + prefs_text})
                except Exception:
                    # Fallback to legacy text if something goes wrong
                    try:
                        if current_prefs:
                            gen_msgs.append({"role": "system", "content": "Existing preferences:\n" + current_prefs})
                    except Exception:
                        pass

                # Provide recent user-only history as context (limit to last 8 user messages)
                # history entries may be (role, msg, ts) so don't unpack incorrectly
                user_msgs = [item[1] for item in history if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == "You"]
                for um in user_msgs[-8:]:
                    gen_msgs.append({"role": "user", "content": um})

                # Also include the current user message explicitly
                gen_msgs.append({"role": "user", "content": message})

                # Try to get extracted preferences from the server
                try:
                    # Route preference-extraction through local or server API depending on settings
                    if 'use_local_var' in globals() and use_local_var.get():
                        gen_text = call_local_openai(gen_msgs)
                    else:
                        gen_text = call_server_api(gen_msgs)
                    extracted = gen_text.strip() if isinstance(gen_text, str) else ''
                except Exception as e:
                    extracted = ''

                if extracted:
                    # New extracted preference lines
                    new_lines = [l.strip() for l in extracted.splitlines() if l.strip()]
                    try:
                        existing = load_prefs_list() or []
                    except Exception:
                        existing = []

                    # Build ordered key list and dict keyed by canonical pref key
                    def pref_key(line):
                        low = line.lower()
                        if ' is ' in low:
                            return low.split(' is ', 1)[0].strip()
                        return low

                    keys = []
                    mapping = {}
                    for item in existing:
                        ln = item.get('line','').strip()
                        if not ln:
                            continue
                        k = pref_key(ln)
                        if k in mapping:
                            # skip duplicates in file, keep first occurrence
                            continue
                        mapping[k] = {'line': ln, 'ts': int(item.get('ts') or int(time.time()))}
                        keys.append(k)

                    # Apply new/updated lines: move updated keys to newest position
                    for nl in new_lines:
                        k = pref_key(nl)
                        entry = {'line': nl, 'ts': int(time.time())}
                        if k in mapping:
                            # remove existing key from keys order then re-append (now newest)
                            try:
                                keys.remove(k)
                            except Exception:
                                pass
                        mapping[k] = entry
                        keys.append(k)

                    # Rebuild final ordered list oldest->newest
                    final = [mapping[k] for k in keys]

                    # Enforce preference entry limit (drop oldest when over limit)
                    try:
                        limit = globals().get('PREFS_LIMIT', PREFS_DEFAULT_LINES)
                        if isinstance(limit, int) and limit >= 0:
                            while len(final) > int(limit):
                                final.pop(0)
                    except Exception:
                        pass

                    # Optionally truncate combined char length to PREFS_MAX_CHARS by trimming oldest
                    try:
                        combined = '\n'.join([f.get('line','') for f in final])
                        if len(combined) > PREFS_MAX_CHARS:
                            # remove oldest entries until under char cap
                            while len(combined) > PREFS_MAX_CHARS and final:
                                final.pop(0)
                                combined = '\n'.join([f.get('line','') for f in final])
                    except Exception:
                        pass

                    # Persist as JSON list of {line, ts}
                    try:
                        save_prefs_list(final)
                    except Exception:
                        pass
            except Exception:
                # If anything in prefs extraction fails, continue without blocking the main request
                pass

            # If preferences file exists now, append its contents as a system message
            try:
                if os.path.exists(PREFS_PATH):
                    with open(PREFS_PATH, 'r', encoding='utf-8') as pf:
                        prefs_text = pf.read().strip()
                        if prefs_text:
                            payload.append({"role": "system", "content": prefs_text})
            except Exception:
                pass

            # Send user message either to the local OpenAI API (gpt-4o-mini) or to the configured server endpoint
            ai_reply = ''
            try:
                print('\nPayload for AI call:', payload, '\n')
                if 'use_local_var' in globals() and use_local_var.get():
                    # Local call using the stored API key
                    ai_reply = call_local_openai(payload)
                else:
                    # Centralized server call
                    ai_reply = call_server_api(payload)
            except Exception:
                # Re-raise to be handled by outer exception handler
                raise

            # Update history (append assistant reply using the active preset label)
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            history.append((preset_label, ai_reply, ts))
            # Also append to the untrimmed full_history for persistence
            full_history.append((preset_label, ai_reply, ts))
            try:
                _trim_history()
            except Exception:
                pass

            # Schedule UI update on main thread: replace the last AI placeholder with real reply
            def on_success():
                # Re-render the chat_area from history to keep it simple and robust
                render_history()
                try:
                    send_btn.config(state=tk.NORMAL)
                except Exception:
                    pass
                # Avoid closing over a name 'entry' from an enclosing scope which
                # may be shadowed by local variables earlier in this function
                # (e.g. during preference merging)
                # Use the global widget reference to ensure we enable the correct Entry widget
                try:
                    ent = globals().get('entry')
                    if ent is not None:
                        ent.config(state=tk.NORMAL)
                except Exception:
                    pass
                try:
                    show_ts_cb.config(state=tk.NORMAL)
                except Exception:
                    pass

            root.after(0, on_success)
        except Exception as e:
            err_text = f"Error: {str(e)}"

            # Append an error entry to history (use preset label)
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            history.append((preset_label, err_text, ts))
            full_history.append((preset_label, err_text, ts))
            try:
                _trim_history()
            except Exception:
                pass
            try:
                _trim_history()
            except Exception:
                pass
    thread = threading.Thread(target=worker, args=(messages_for_gpt,), daemon=True)
    thread.start()


def get_saved_api_key():
    """Return an API key stored in settings.json or None."""
    try:
        loaded = load_settings()
        if isinstance(loaded, dict):
            key = loaded.get('openai_api_key')
            if key:
                return key
    except Exception:
        pass
    return None


def _atomic_write(path: str, text: str, mode: int = 0o600):
    """Write text atomically to path and set permissions.
    Uses a tmp file + os.replace and attempts fsync; best-effort chmod.
    """
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as tf:
            tf.write(text)
            tf.flush()
            try:
                os.fsync(tf.fileno())
            except Exception:
                pass
        os.replace(tmp, path)
        try:
            os.chmod(path, mode)
        except Exception:
            pass
    except Exception:
        # Best-effort only, don't raise to avoid breaking startup
        pass


def save_settings(use_local: bool, api_key: str | None = None, endpoint: str | None = None, last_deleted: str | None = None, ai_history_lines: int | None = None, pref_memory_lines: int | None = None):
    """Persist settings to SETTINGS_PATH.

    Arguments:
    - use_local: whether to enable local OpenAI usage
    - api_key: if provided:
        - a non-empty string will store the API key in settings.json
        - an empty string ('') will remove any stored key from settings.json
        - None will leave existing openai_api_key in settings.json untouched
    """
    try:
        # Load existing settings to preserve unrelated fields
        data = {}
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, 'r', encoding='utf-8') as sf:
                    data = json.load(sf) or {}
        except Exception:
            data = {}
        data['use_local_ai'] = bool(use_local)
        if api_key is not None:
            if api_key:
                data['openai_api_key'] = api_key
            else:
                # remove stored key
                data.pop('openai_api_key', None)
        if endpoint is not None:
            if endpoint:
                data['server_endpoint'] = endpoint
            else:
                data.pop('server_endpoint', None)
        # Record which credential was deleted most recently (if provided)
        # Use a stable key name so startup logic can prefer prompting the
        # most recently removed credential when both are missing
        if last_deleted is not None:
            if last_deleted:
                data['last_credential_deleted'] = str(last_deleted)
                try:
                    data['last_credential_deleted_ts'] = int(time.time())
                except Exception:
                    pass
            else:
                data.pop('last_credential_deleted', None)
                data.pop('last_credential_deleted_ts', None)
        # Persist an optional AI history-lines limit so the UI can round-trip
        # the user's choice. If ai_history_lines is None we leave the value
        # unchanged; an explicit integer will be stored (and should be a
        # small non-negative number)
        if ai_history_lines is not None:
            try:
                data['ai_history_lines'] = int(ai_history_lines)
            except Exception:
                # ignore invalid values
                pass
        # Persist preference memory limit if provided
        if pref_memory_lines is not None:
            try:
                data['pref_memory_lines'] = int(pref_memory_lines)
            except Exception:
                pass
        _atomic_write(SETTINGS_PATH, json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass


def load_settings():
    """Return stored settings dict or defaults.

    Also returns any metadata about the last deleted credential so startup
    logic can prefer prompting for the most recently removed credential.
    """
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, 'r', encoding='utf-8') as sf:
                loaded = json.load(sf)
            return {
                'use_local_ai': bool(loaded.get('use_local_ai', True)),
                'openai_api_key': loaded.get('openai_api_key'),
                'server_endpoint': loaded.get('server_endpoint'),
                'last_credential_deleted': loaded.get('last_credential_deleted'),
                'last_credential_deleted_ts': loaded.get('last_credential_deleted_ts'),
                'ai_history_lines': loaded.get('ai_history_lines'),
                'pref_memory_lines': loaded.get('pref_memory_lines')
            }
    except Exception:
        pass
    return {'use_local_ai': True, 'openai_api_key': None, 'server_endpoint': None, 'last_credential_deleted': None, 'ai_history_lines': None, 'pref_memory_lines': None}


def call_local_openai(messages_for_gpt):
    """Call OpenAI's chat completions API (gpt-4o-mini) using the stored API key.
    Returns the assistant reply string.
    """
    OPENAI_API_KEY = get_saved_api_key()
    if not OPENAI_API_KEY:
        raise RuntimeError('No OpenAI API key available for local calls')
    try:
        url = 'https://api.openai.com/v1/chat/completions'
        headers = {'Authorization': f'Bearer {OPENAI_API_KEY}', 'Content-Type': 'application/json'}
        payload = {'model': 'gpt-4o-mini', 'messages': messages_for_gpt}
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # Try to extract assistant content in common OpenAI response shapes
        content = ''
        if isinstance(data, dict):
            # completion-style
            choices = data.get('choices') or []
            if choices and isinstance(choices, list):
                first = choices[0]
                # newer responses have 'message' dict
                msg = first.get('message') if isinstance(first, dict) else None
                if isinstance(msg, dict):
                    content = msg.get('content', '')
                else:
                    # older shape: 'text'
                    content = first.get('text', '')
        return content or ''
    except Exception as e:
        raise


def call_server_api(messages_for_gpt):
    """Send messages to the configured server endpoint and return the assistant reply string.
    This centralizes the inlined requests.post call so both pathways live next to each other.
    """
    try:
        # Prefer any user-configured endpoint stored in settings.json
        ep = get_saved_endpoint() or endpoint
        resp = requests.post(ep, json={'messages': messages_for_gpt}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get('response', '') if isinstance(data, dict) else ''
    except Exception:
        raise

def prompt_for_api_key():
    """Ensure an OpenAI API key is available: if missing, show a centered modal
    dialog that cannot be closed until the user supplies (and saves) a key.
    """
    global OPENAI_API_KEY
    try:
        key = get_saved_api_key()
        if key:
            OPENAI_API_KEY = key
            return

        # No saved key - force a centered, modal, non-closable dialog
        dlg = tk.Toplevel(root)
        dlg.title('OpenAI API Key Required')
        try:
            dlg.transient(root)
        except Exception:
            pass
        dlg.resizable(False, False)

        # Disable window close and Escape key so the dialog cannot be dismissed
        dlg.protocol('WM_DELETE_WINDOW', lambda: None)
        dlg.bind('<Escape>', lambda e: None)

        tk.Label(dlg, text='An OpenAI API key is required to run locally. Please enter it to continue.', wraplength=420, justify='left').pack(padx=16, pady=(12,6))
        key_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=key_var, show='*', width=56)
        entry.pack(padx=16, pady=(0,8))

        info_lbl = tk.Label(dlg, text='The key will be saved locally to allow offline use of OpenAI. It will not be displayed again.', wraplength=420, justify='left', fg='gray40')
        info_lbl.pack(padx=16, pady=(0,8))

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=(6,14))

        save_btn = tk.Button(btn_frame, text='Save and continue', state=tk.DISABLED)
        save_btn.pack(side=tk.LEFT, padx=6)

        def on_change(*_):
            val = key_var.get().strip()
            try:
                save_btn.config(state=tk.NORMAL if val else tk.DISABLED)
            except Exception:
                pass

        def on_save():
            val = key_var.get().strip()
            if not val:
                return
            # Persist key into settings.json
            try:
                save_settings(True, api_key=val)
            except Exception:
                pass
            try:
                # set global so other code can read it immediately
                nonlocal_dummy = None
            except Exception:
                pass
            OPENAI_API_KEY = val
            try:
                dlg.destroy()
            except Exception:
                pass

        save_btn.config(command=on_save)
        key_var.trace_add('write', on_change)

        # Center the dialog on screen after geometry settles
        dlg.update_idletasks()
        ww = dlg.winfo_width()
        wh = dlg.winfo_height()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)
        try:
            dlg.geometry(f'+{x}+{y}')
        except Exception:
            pass

        # Make modal and block until a key is saved
        try:
            dlg.grab_set()
            entry.focus_force()
            root.wait_window(dlg)
        except Exception:
            try:
                root.wait_window(dlg)
            except Exception:
                pass
    except Exception:
        OPENAI_API_KEY = get_saved_api_key()


def get_saved_endpoint():
    """Return the saved server endpoint from settings.json or None."""
    try:
        loaded = load_settings()
        if isinstance(loaded, dict):
            ep = loaded.get('server_endpoint')
            if ep:
                return ep
    except Exception:
        pass
    return None


def prompt_for_endpoint():
    """Prompt the user for a server endpoint when server mode is entered and none is configured."""
    global endpoint
    try:
        ep = get_saved_endpoint()
        if ep:
            endpoint = ep
            return

        dlg = tk.Toplevel(root)
        dlg.title('Server Endpoint Required')
        try:
            dlg.transient(root)
        except Exception:
            pass
        dlg.resizable(False, False)
        dlg.protocol('WM_DELETE_WINDOW', lambda: None)
        dlg.bind('<Escape>', lambda e: None)

        tk.Label(dlg, text='A server endpoint is required for server mode. Enter the full URL (e.g. http://host:port/chat):', wraplength=420, justify='left').pack(padx=16, pady=(12,6))
        ep_var = tk.StringVar()
        entry = tk.Entry(dlg, textvariable=ep_var, width=60)
        entry.pack(padx=16, pady=(0,8))

        btn_frame = tk.Frame(dlg)
        btn_frame.pack(pady=(6,14))
        save_btn = tk.Button(btn_frame, text='Save and continue', state=tk.DISABLED)
        save_btn.pack(side=tk.LEFT, padx=6)

        def on_change(*_):
            val = ep_var.get().strip()
            try:
                save_btn.config(state=tk.NORMAL if val else tk.DISABLED)
            except Exception:
                pass

        def on_save():
            val = ep_var.get().strip()
            if not val:
                return
            try:
                # Persist endpoint into settings.json
                save_settings(False, endpoint=val)
            except Exception:
                pass
            try:
                endpoint = val
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        save_btn.config(command=on_save)
        ep_var.trace_add('write', on_change)

        dlg.update_idletasks()
        ww = dlg.winfo_width()
        wh = dlg.winfo_height()
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max(0, (sw - ww) // 2)
        y = max(0, (sh - wh) // 2)
        try:
            dlg.geometry(f'+{x}+{y}')
        except Exception:
            pass

        try:
            dlg.grab_set()
            entry.focus_force()
            root.wait_window(dlg)
        except Exception:
            try:
                root.wait_window(dlg)
            except Exception:
                pass
    except Exception:
        # fallback - leave global endpoint as-is
        try:
            endpoint = endpoint
        except Exception:
            pass

def load_history():
    # Use the central render function which handles enabling/disabling the widget
    render_history()


def new_conversation():
    if messagebox.askyesno("New Conversation", "Start a new conversation? This will clear the current chat history."):
        history.clear()
        full_history.clear()
        # Re-render (will clear the display and keep widget state consistent)
        render_history()
        set_conversation_title('New Conversation')
        # Reset saved-state tracking
        try:
            global current_conversation_path, unsaved_changes
            current_conversation_path = None
            unsaved_changes = False
        except Exception:
            pass


def save_conversation():
    # Default to the 'conversations' folder next to the script
    conv_dir = os.path.join(os.path.dirname(__file__), 'conversations')
    try:
        os.makedirs(conv_dir, exist_ok=True)
    except Exception:
        pass
    path = filedialog.asksaveasfilename(initialdir=conv_dir, defaultextension='.json', filetypes=[('JSON files','*.json'), ('All files','*.*')])
    if not path:
        return False
    try:
        # Save the full, untrimmed conversation (full_history)
        serial = []
        for item in full_history:
            if isinstance(item, (list, tuple)):
                serial.append(list(item))
            else:
                serial.append([str(item)])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)
        # Update conversation title to the saved filename (strip directory and extension)
        try:
            fname = os.path.basename(path)
            set_conversation_title(fname)
        except Exception:
            pass
        # update saved-state tracking
        try:
            global current_conversation_path, unsaved_changes
            current_conversation_path = path
            unsaved_changes = False
        except Exception:
            pass
        messagebox.showinfo('Saved', f'Conversation saved to {path}')
        return True
    except Exception as e:
        messagebox.showerror('Save error', str(e))
        return False


def load_conversation_file():
    # Default to the 'conversations' folder next to the script
    conv_dir = os.path.join(os.path.dirname(__file__), 'conversations')
    try:
        os.makedirs(conv_dir, exist_ok=True)
    except Exception:
        pass
    path = filedialog.askopenfilename(initialdir=conv_dir, filetypes=[('JSON files','*.json'), ('All files','*.*')])
    if not path:
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Expecting a list of [role, message] pairs
        if isinstance(data, list):
            history.clear()
            full_history.clear()
            for item in data:
                # item may be [role, message] or [role, message, timestamp]
                if isinstance(item, list) or isinstance(item, tuple):
                    if len(item) >= 2:
                        role = item[0]
                        msg = item[1]
                        ts = item[2] if len(item) > 2 else time.strftime('%Y-%m-%d %H:%M:%S')
                        history.append((role, msg, ts))
                        full_history.append((role, msg, ts))
            render_history()
            set_conversation_title(os.path.basename(path))
            # update saved-state tracking
            try:
                global current_conversation_path, unsaved_changes
                current_conversation_path = path
                unsaved_changes = False
            except Exception:
                pass
            messagebox.showinfo('Loaded', f'Conversation loaded from {path}')
    except Exception as e:
        messagebox.showerror('Load error', str(e))

def limit_chat():
    try:
        # Determine current value (fallback to 10 if not set)
        cur = globals().get('HISTORY_LIMIT', None)
        if cur is None:
            try:
                loaded = load_settings() or {}
                cur = int(loaded.get('ai_history_lines') or 10)
            except Exception:
                cur = 10
        # Ask the user for an integer limit (0..50)
        val = tk.simpledialog.askinteger('AI Chat Memory Limit', 'Number of recent chat lines to include when sending context to the AI (0 = only current message):', parent=root, minvalue=0, maxvalue=50, initialvalue=cur)
        if val is None:
            return
        # Persist the setting while preserving other settings
        try:
            cur_use = use_local_var.get() if 'use_local_var' in globals() and isinstance(use_local_var, tk.BooleanVar) else True
        except Exception:
            cur_use = True
        try:
            save_settings(bool(cur_use), ai_history_lines=int(val))
        except Exception:
            pass
        # Update runtime limit
        try:
            globals()['HISTORY_LIMIT'] = int(val)
        except Exception:
            globals()['HISTORY_LIMIT'] = cur
        # messagebox.showinfo('AI Chat Memory Limit', f'AI history limit set to {val} lines')
        messagebox.showinfo('AI Chat Memory Limit', 'AI short-term memory updated.')
    except Exception as e:
        try:
            messagebox.showerror('AI Chat Memory Limit', str(e))
        except Exception:
            pass

def limit_prefs():
    try:
        # Determine current value (fallback to PREFS_LIMIT or default)
        cur = globals().get('PREFS_LIMIT', None)
        if cur is None:
            try:
                loaded = load_settings() or {}
                cur = int(loaded.get('pref_memory_lines') or PREFS_DEFAULT_LINES)
            except Exception:
                cur = PREFS_DEFAULT_LINES
        # Ask the user for an integer limit (0..500)
        val = tk.simpledialog.askinteger('AI Preference Memory Limit', 'Maximum number of preference lines to retain (oldest are dropped when exceeded):', parent=root, minvalue=0, maxvalue=500, initialvalue=cur)
        if val is None:
            return
        # Persist the setting while preserving other settings
        try:
            cur_use = use_local_var.get() if 'use_local_var' in globals() and isinstance(use_local_var, tk.BooleanVar) else True
        except Exception:
            cur_use = True
        try:
            save_settings(bool(cur_use), pref_memory_lines=int(val))
        except Exception:
            pass
        # Update runtime limit
        try:
            globals()['PREFS_LIMIT'] = int(val)
        except Exception:
            globals()['PREFS_LIMIT'] = cur
        try:
            messagebox.showinfo('AI Preference Memory Limit', 'Preference memory limit updated.')
        except Exception:
            pass
    except Exception as e:
        try:
            messagebox.showerror('AI Preference Memory Limit', str(e))
        except Exception:
            pass

def clear_prefs():
    try:
        if not os.path.exists(PREFS_PATH):
            messagebox.showinfo('Preferences', 'No preferences file to delete')
            return
        # Ask for confirmation before deleting the preferences file
        try:
            preset_label = determine_active_preset_name()
        except Exception:
            preset_label = 'saved preferences'

        confirm_msg = f"This app automatically detects and writes your preferences to a file for future reference by {preset_label}. Are you sure you want to delete this file? This will remove all of your saved preferences and cannot be undone."
        if not messagebox.askyesno('Confirm', confirm_msg):
            return
        os.remove(PREFS_PATH)
        messagebox.showinfo('Preferences', 'Preferences cleared.')
    except Exception as e:
        messagebox.showerror('Error', str(e))

# GUI Setup
root = tk.Tk()
root.title("Chat Test")
root.geometry("800x600")

# Menu bar
menubar = tk.Menu(root)
file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label='New...', command=new_conversation)
file_menu.add_command(label='Save...', command=save_conversation)
file_menu.add_command(label='Load...', command=load_conversation_file)
file_menu.add_separator()
def on_exit():
    # If there are unsaved changes, prompt the user to save
    try:
        if unsaved_changes:
            resp = messagebox.askyesnocancel('Save before exit', 'You have unsaved changes. Save before exiting?')
            # Yes -> attempt save; if save succeeds exit, otherwise abort
            if resp is True:
                ok = save_conversation()
                if ok:
                    root.destroy()
                else:
                    return
            # No -> exit without saving
            elif resp is False:
                root.destroy()
            # Cancel -> do nothing
            else:
                return
        else:
            root.destroy()
    except Exception:
        try:
            root.destroy()
        except Exception:
            pass

file_menu.add_command(label='Exit', command=on_exit)
menubar.add_cascade(label='Conversation', menu=file_menu)
root.config(menu=menubar)

# Prompt to save on window close
root.protocol('WM_DELETE_WINDOW', on_exit)

# Add Personality menu entry (opens a separate window)
def open_personality_window():
    # Reuse global vars and build a Toplevel window with sliders
    if getattr(open_personality_window, 'win', None) and open_personality_window.win.winfo_exists():
        try:
            # If it's minimized or hidden, restore it
            open_personality_window.win.deiconify()
        except Exception:
            pass
        try:
            open_personality_window.win.lift()
            open_personality_window.win.focus_force()
            # Temporary topmost toggle helps on some window managers to raise the window
            try:
                open_personality_window.win.attributes('-topmost', True)
                open_personality_window.win.after(50, lambda w=open_personality_window.win: w.attributes('-topmost', False))
            except Exception:
                pass
        except Exception:
            pass
        return
    win = tk.Toplevel(root)
    win.title('Personality')
    # Make this Toplevel transient to the main window so the window manager treats it as a child
    try:
        win.transient(root)
    except Exception:
        pass
    # Do not hardcode geometry so the window can adapt to scaling, but with a reasonable minimum
    win.minsize(320, 300)
    open_personality_window.win = win

    tk.Label(win, text='Personality', font=(None, 12, 'bold')).pack(pady=(6,4))

    # Presets map - name, tuple of slider values
    presets = {
        'Default AI': (2, 1, 0, 30, 1, 0, 0, 1),
        'Helpful Professional': (2, 2, 0, 35, 1, 0, 0, 1),
        'Casual Friendly': (3, 0, 0, 25, 1, 1, 0, 1),
        'Playful Sarcastic': (2, 0, 1, 18, 1, 2, 2, 1),
        'Child-Friendly': (3, 1, 0, 12, 1, 0, 0, 2),
        'Stoic Professional': (1, 2, 0, 40, 1, 0, 0, 0),
        'Sailor-Mouth': (0, 0, 2, 30, 1, 1, 2, 0),
    }

    # Presets file/dir paths
    presets_path = os.path.join(os.path.dirname(__file__), 'presets.json')
    presets_dir = os.path.join(os.path.dirname(__file__), 'personalities')
    try:
        os.makedirs(presets_dir, exist_ok=True)
    except Exception:
        pass

    # Load any per-file presets from the personalities/ directory
    try:
        for fname in os.listdir(presets_dir):
            if not fname.lower().endswith('.json'):
                continue
            name = os.path.splitext(fname)[0]
            full = os.path.join(presets_dir, fname)
            try:
                with open(full, 'r', encoding='utf-8') as pf:
                    loaded = json.load(pf)
                # Support either a list of values or an object with 'values'
                vals = None
                if isinstance(loaded, list):
                    vals = loaded
                elif isinstance(loaded, dict) and 'values' in loaded:
                    vals = loaded.get('values')
                if vals and len(vals) >= 8:
                    presets[name] = tuple(int(x) for x in vals[:8])
            except Exception:
                continue
    except Exception:
        pass

    # Try to load last_selected from presets.json (keeps only the last selection)
    try:
        if os.path.exists(presets_path):
            with open(presets_path, 'r', encoding='utf-8') as pf:
                loaded = json.load(pf)
            last_selected = loaded.get('last_selected') if isinstance(loaded, dict) else None
        else:
            last_selected = None
    except Exception:
        last_selected = None

    # Include a 'Custom' label for when slider values don't match any listed preset
    preset_var = tk.StringVar(value=last_selected if (last_selected in presets) else 'Custom')
    # Update the shared summary label and the local window label
    def apply_changes():
        # Read current slider vars into the shared summary and local summary
        update_summary()
        try:
            win_summary.config(text=summary_label.cget('text'))
        except tk.TclError:
            pass

    def apply_preset(name):
        # Apply the preset tuple to the personality variables and update summaries
        vals = presets.get(name)
        if not vals:
            return
        try:
            friendliness_var.set(vals[0])
            professionalism_var.set(vals[1])
            profanity_var.set(vals[2])
            age_var.set(vals[3])
            gender_var.set(vals[4])
            humor_var.set(vals[5])
            sarcasm_var.set(vals[6])
            introversion_var.set(vals[7])
        except Exception:
            # If any var is missing for some reason, ignore and continue
            pass
        # Update the shared and local summaries
        apply_changes()

    tk.Label(win, text='Presets').pack(anchor='w', padx=8, pady=(4,0))
    # OptionMenu options - show 'Custom' plus all preset names
    option_names = ['Custom'] + list(presets.keys())
    preset_menu = tk.OptionMenu(win, preset_var, *option_names, command=apply_preset)
    preset_menu.pack(fill=tk.X, padx=8)

    def update_preset_menu():
        # Rebuild the OptionMenu items to reflect current presets dict
        menu = preset_menu['menu']
        menu.delete(0, 'end')
        menu.add_command(label='Custom', command=lambda v='Custom': preset_var.set(v))
        for name in sorted(presets.keys()):
            menu.add_command(label=name, command=lambda v=name: (preset_var.set(v), apply_preset(v)))

    def save_preset_to_file():
        # Ask for a filename to save the current slider configuration
        tpl = current_values_tuple()
        name = tk.simpledialog.askstring('Save preset', 'Preset name (file will be saved as <name>.json):')
        if not name:
            return
        fname = name.strip()
        if not fname:
            return
        full = os.path.join(presets_dir, f"{fname}.json")
        data = {'values': list(tpl)}
        try:
            tmp = full + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as pf:
                json.dump(data, pf, ensure_ascii=False, indent=2)
                pf.flush()
                try:
                    os.fsync(pf.fileno())
                except Exception:
                    pass
            os.replace(tmp, full)
            # Add to presets dict and refresh menu
            presets[fname] = tpl
            update_preset_menu()
            preset_var.set(fname)
            apply_preset(fname)
        except Exception as e:
            messagebox.showerror('Save error', str(e))

    def load_preset_from_file():
        # Parent the file dialog so the OS places it above the personality window
        try:
            path = filedialog.askopenfilename(initialdir=presets_dir, filetypes=[('JSON files','*.json'), ('All files','*.*')], parent=win)
        except Exception:
            path = filedialog.askopenfilename(initialdir=presets_dir, filetypes=[('JSON files','*.json'), ('All files','*.*')])
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as pf:
                loaded = json.load(pf)
            vals = None
            if isinstance(loaded, list):
                vals = loaded
            elif isinstance(loaded, dict) and 'values' in loaded:
                vals = loaded.get('values')
            if vals and len(vals) >= 8:
                name = os.path.splitext(os.path.basename(path))[0]
                presets[name] = tuple(int(x) for x in vals[:8])
                update_preset_menu()
                preset_var.set(name)
                apply_preset(name)
        except Exception as e:
            messagebox.showerror('Load error', str(e))

    # Small controls to save/load preset files
    ctrl_frame = tk.Frame(win)
    ctrl_frame.pack(fill=tk.X, padx=8, pady=(4,6))
    tk.Button(ctrl_frame, text='Save Preset...', command=save_preset_to_file).pack(side=tk.LEFT)
    tk.Button(ctrl_frame, text='Load Preset...', command=load_preset_from_file).pack(side=tk.LEFT, padx=(6,0))

    # Helper to read current slider values as a tuple
    def current_values_tuple():
        return (
            int(friendliness_var.get()), int(professionalism_var.get()), int(profanity_var.get()),
            int(age_var.get()), int(gender_var.get()), int(humor_var.get()), int(sarcasm_var.get()), int(introversion_var.get())
        )

    def find_matching_preset(tpl):
        for name, vals in presets.items():
            if tuple(vals) == tuple(tpl):
                return name
        return 'Custom'

    # Called when a Scale is manipulated by the user, update summary and preset selector
    def on_slider_change(_=None):
        try:
            update_summary()
        except Exception:
            pass
        try:
            # update local summary label if present
            win_summary.config(text=summary_label.cget('text'))
        except Exception:
            pass
        try:
            preset_var.set(find_matching_preset(current_values_tuple()))
        except Exception:
            try:
                preset_var.set('Custom')
            except Exception:
                pass
        # Update any mixer value labels if present
        try:
            for var_obj, lbl in value_label_pairs:
                try:
                    lbl.config(text=str(var_obj.get()))
                except Exception:
                    pass
        except Exception:
            pass

    # Mixer-style layout, vertical sliders arranged horizontally to use widescreen space
    mixer_frame = tk.Frame(win)
    mixer_frame.pack(fill=tk.X, padx=8, pady=(6,4))

    # Define fields as (label, variable, min, max)
    # The last slider is 'Extroversion' conceptually (higher = more extroverted), but introversion was just kept for backwards compatibility
    mixer_fields = [
        ('Friendliness', friendliness_var, 0, 3),
        ('Professionalism', professionalism_var, 0, 2),
        ('Profanity', profanity_var, 0, 2),
        ('Age', age_var, 5, 127),
        ('Gender', gender_var, 0, 2),
        ('Humour', humor_var, 0, 2),
        ('Sarcasm', sarcasm_var, 0, 2),
        ('Extroversion', introversion_var, 0, 2),
    ]

    # List of (tk.Variable, label widget) pairs for live updates
    value_label_pairs = []

    # Reflow mixer into two rows x four columns to make the window narrower
    scale_length = 120
    cols = 4
    rows = (len(mixer_fields) + cols - 1) // cols
    # Configure column sizes
    for c in range(cols):
        try:
            mixer_frame.columnconfigure(c, weight=1, minsize=scale_length + 12)
        except Exception:
            pass

    for idx, (label_text, var_obj, vmin, vmax) in enumerate(mixer_fields):
        row = idx // cols
        col = idx % cols
        col_frame = tk.Frame(mixer_frame, width=scale_length)
        col_frame.grid(row=row, column=col, padx=6, pady=4, sticky='n')
        lbl = tk.Label(col_frame, text=label_text, font=(None, 9), wraplength=scale_length, justify='center')
        lbl.grid(row=0, column=0, pady=(0,6))
        scale = tk.Scale(col_frame, from_=vmax, to=vmin, orient=tk.VERTICAL,
                         variable=var_obj, command=on_slider_change, length=scale_length)
        scale.grid(row=1, column=0)
        val_lbl = tk.Label(col_frame, text=str(var_obj.get()), font=(None, 9))
        val_lbl.grid(row=2, column=0, pady=(6,0))
        value_label_pairs.append((var_obj, val_lbl))

    # Summary shown in the window too (wraplength will be updated on resize)
    # Slightly smaller and greyed to be less prominent
    win_summary = tk.Label(win, text='', wraplength=280, justify='left', font=(None, 9, 'italic'), fg='gray40')
    win_summary.pack(padx=8, pady=10, fill=tk.X)

    # Update the shared summary label and the local window label
    def apply_changes():
        # Read current slider vars into the shared summary and local summary
        update_summary()
        try:
            win_summary.config(text=summary_label.cget('text'))
        except tk.TclError:
            pass

    # Initialize window summary
    win_summary.config(text=summary_label.cget('text'))

    # Ensure the preset selector matches the current slider values on open
    def current_values_tuple():
        return (
            int(friendliness_var.get()), int(professionalism_var.get()), int(profanity_var.get()),
            int(age_var.get()), int(gender_var.get()), int(humor_var.get()), int(sarcasm_var.get()), int(introversion_var.get())
        )

    def find_matching_preset(tpl):
        for name, vals in presets.items():
            if tuple(vals) == tuple(tpl):
                return name
        return 'Custom'

    # If last_selected was saved and exists, keep it, otherwise try to match current sliders
    if preset_var.get() not in presets:
        preset_var.set(find_matching_preset(current_values_tuple()))

    # Make the summary wrap adaptively when the Toplevel is resized
    def on_win_configure(event):
        # leave some padding (16px each side)
        new_wrap = max(100, event.width - 32)
        try:
            win_summary.config(wraplength=new_wrap)
        except tk.TclError:
            # If the widget no longer exists, ignore
            pass

    win.bind('<Configure>', on_win_configure)

    # Save presets and last selection when the window closes
    def on_close():
        # Determine which preset best matches current sliders
        tpl = current_values_tuple()
        matched = find_matching_preset(tpl)
        last = matched if matched in presets else 'Custom'
        data = {'presets': {k: list(v) for k, v in presets.items()}, 'last_selected': last}
        try:
            tmp_path = presets_path + '.tmp'
            with open(tmp_path, 'w', encoding='utf-8') as pf:
                json.dump(data, pf, ensure_ascii=False, indent=2)
                pf.flush()
                try:
                    os.fsync(pf.fileno())
                except Exception:
                    pass
            os.replace(tmp_path, presets_path)
        except Exception as e:
            print('[presets] failed to write presets:', e)
        try:
            win.destroy()
        except Exception:
            pass

    win.protocol('WM_DELETE_WINDOW', on_close)

personality_menu = tk.Menu(menubar, tearoff=0)
personality_menu.add_command(label='Configure...', command=open_personality_window)
menubar.add_cascade(label='Personality', menu=personality_menu)

# Settings menu
settings_menu = tk.Menu(menubar, tearoff=0)
# Ensure use_local_var exists (loaded earlier near UI setup, if not, provide default)
if 'use_local_var' not in globals():
    try:
        _loaded_settings = load_settings()
        use_local_var = tk.BooleanVar(value=bool(_loaded_settings.get('use_local_ai', True)))
    except Exception:
        use_local_var = tk.BooleanVar(value=True)

def manage_api_key():
    """Open a dialog to view/update/delete the stored OpenAI API key."""
    try:
        # Determine current saved key (from settings.json)
        file_key = None
        try:
            loaded = load_settings()
            file_key = loaded.get('openai_api_key') if isinstance(loaded, dict) else None
        except Exception:
            file_key = None

        def save_new(k):
            """Persist a new key or remove it when k is None or empty string."""
            try:
                if k is None or (isinstance(k, str) and not k.strip()):
                    # Remove stored key
                    try:
                        save_settings(True if 'use_local_var' in globals() and use_local_var.get() else False, api_key='')
                    except Exception:
                        pass
                    try:
                        globals()['OPENAI_API_KEY'] = None
                    except Exception:
                        pass
                    try:
                        messagebox.showinfo('API Key', 'API key removed from disk and settings. Local mode has been disabled.')
                    except Exception:
                        pass
                    try:
                        if not get_saved_api_key() and not get_saved_endpoint():
                            prompt_for_api_key()
                    except Exception:
                        pass
                    return
                # Save provided key
                try:
                    save_settings(True, api_key=str(k).strip())
                except Exception:
                    pass
                try:
                    globals()['OPENAI_API_KEY'] = str(k).strip()
                except Exception:
                    pass
                try:
                    messagebox.showinfo('API Key', 'API key saved to disk and settings.')
                except Exception:
                    pass
            except Exception:
                pass

        # Build the dialog
        dlg = tk.Toplevel(root)
        dlg.title('API Key')
        try:
            dlg.transient(root)
        except Exception:
            pass
        tk.Label(dlg, text='OpenAI API Key (leave empty and click Save to delete existing):').pack(padx=12, pady=(10,4), anchor='w')
        entry_val = tk.StringVar()
        entry_val.set('')
        ent = tk.Entry(dlg, textvariable=entry_val, width=60, show='*')
        ent.pack(padx=12, pady=(0,6))

        if file_key:
            info_txt = 'A saved API key is present (not shown). Enter a new key to replace it, or leave the field empty and click Save to delete it.'
        else:
            info_txt = 'Enter your OpenAI API key and click Save.'
        tk.Label(dlg, text=info_txt, wraplength=420, justify='left', fg='gray40').pack(padx=12, pady=(0,6), anchor='w')

        def on_save():
            val = ent.get().strip()
            if val == '':
                # User submitted an empty string -> confirm deletion if a key exists
                if file_key:
                    try:
                        if messagebox.askyesno('Confirm', 'Remove saved API key from disk?'):
                            save_new(None)
                            try:
                                dlg.destroy()
                            except Exception:
                                pass
                            return
                        else:
                            # Leave dialog open
                            return
                    except Exception:
                        return
                else:
                    # No stored key and empty input -> nothing to save
                    try:
                        dlg.destroy()
                    except Exception:
                        pass
                    return
            # Save provided key
            save_new(val)
            try:
                dlg.destroy()
            except Exception:
                pass

        def on_remove():
            # Explicit remove button (same behavior as saving empty)
            try:
                if messagebox.askyesno('Confirm', 'Remove saved API key from disk?'):
                    save_new(None)
                    try:
                        dlg.destroy()
                    except Exception:
                        pass
            except Exception:
                pass

        btnf = tk.Frame(dlg)
        btnf.pack(pady=(6,12))
        tk.Button(btnf, text='Save', command=on_save, width=10).pack(side=tk.LEFT, padx=6)
        tk.Button(btnf, text='Cancel', command=lambda: dlg.destroy(), width=10).pack(side=tk.LEFT, padx=6)
        ent.focus_force()
        try:
            dlg.grab_set()
            root.wait_window(dlg)
        except Exception:
            try:
                root.wait_window(dlg)
            except Exception:
                pass
    except Exception as e:
        try:
            messagebox.showerror('API Key', str(e))
        except Exception:
            pass


def manage_endpoint():
    """Open a dialog to view/update/delete the configured server endpoint."""
    try:
        # Load current endpoint from settings (no legacy file)
        cur = None
        try:
            cur = get_saved_endpoint()
        except Exception:
            cur = None

        def save_new(ep):
            if ep is None or not ep.strip():
                # Remove endpoint from settings
                try:
                    # Mark that the server endpoint was the most recently deleted
                    save_settings(True if 'use_local_var' in globals() and use_local_var.get() else False, endpoint='', last_deleted='server_endpoint')
                except Exception:
                    pass
                try:
                    # If endpoint is removed, switch to local mode
                    if 'use_local_var' in globals() and isinstance(use_local_var, tk.BooleanVar):
                        use_local_var.set(True)
                except Exception:
                    pass
                messagebox.showinfo('Server endpoint', 'Server endpoint removed. Server mode has been disabled.')
                # If both credentials are now missing, prefer prompting for the
                # most recently deleted one
                try:
                    if not get_saved_api_key() and not get_saved_endpoint():
                        prompt_for_endpoint()
                except Exception:
                    pass
                return
            try:
                save_settings(False if 'use_local_var' in globals() and not use_local_var.get() else use_local_var.get(), endpoint=ep.strip())
            except Exception:
                pass
            messagebox.showinfo('Server endpoint', 'Server endpoint saved to disk and settings.')

        dlg = tk.Toplevel(root)
        dlg.title('Server endpoint')
        try:
            dlg.transient(root)
        except Exception:
            pass
        tk.Label(dlg, text='Server endpoint URL (leave empty to remove):').pack(padx=12, pady=(10,4), anchor='w')
        entry_val = tk.StringVar()
        if cur:
            entry_val.set(cur)
        else:
            entry_val.set('')
        ent = tk.Entry(dlg, textvariable=entry_val, width=60)
        ent.pack(padx=12, pady=(0,6))

        def on_save():            
            val = ent.get().strip()
            if val == '':
                if messagebox.askyesno('Confirm', 'Remove saved server endpoint from settings?'):
                    save_new(None)
                    try:
                        dlg.destroy()
                    except Exception:
                        pass
                return
            save_new(val)
            try:
                dlg.destroy()
            except Exception:
                pass

        btnf = tk.Frame(dlg)
        btnf.pack(pady=(6,12))
        tk.Button(btnf, text='Save', command=on_save, width=10).pack(side=tk.LEFT, padx=6)
        tk.Button(btnf, text='Cancel', command=lambda: dlg.destroy(), width=10).pack(side=tk.LEFT, padx=6)
        ent.focus_force()
        try:
            dlg.grab_set()
            root.wait_window(dlg)
        except Exception:
            try:
                root.wait_window(dlg)
            except Exception:
                pass
    except Exception as e:
        messagebox.showerror('Server endpoint', str(e))


def toggle_use_local():
    try:
        val = bool(use_local_var.get())
        # Persist the toggle (leave api_key/endpoint untouched)
        save_settings(val)
        # If enabling local mode and no key exists, prompt for it immediately
        if val and not get_saved_api_key():
            try:
                prompt_for_api_key()
            except Exception:
                pass
        # If enabling server mode and no endpoint exists, prompt for it
        if not val:
            try:
                if not get_saved_endpoint():
                    prompt_for_endpoint()
            except Exception:
                pass
    except Exception:
        pass

settings_menu.add_checkbutton(label='Use Local OpenAI API Key', variable=use_local_var, command=toggle_use_local)
settings_menu.add_command(label='API Key...', command=manage_api_key)
settings_menu.add_command(label='Server Endpoint...', command=lambda: manage_endpoint())
settings_menu.add_separator()
settings_menu.add_command(label='AI Chat Memory Limit...', command=limit_chat)
settings_menu.add_command(label='AI Preference Memory Limit...', command=limit_prefs)
settings_menu.add_command(label='Clear Preferences...', command=clear_prefs)
menubar.add_cascade(label='Settings', menu=settings_menu)

# Trimmed history sent to the AI (kept short for context). full_history stores the complete
# conversation (untrimmed) and is what we persist when saving conversations
history = []  # Chat history (10 pairs max)
full_history = []  # Complete conversation log (untrimmed), saved to conversations/
# Track the current conversation file path (None for a new/unsaved conversation)
current_conversation_path = None
# Track whether there are unsaved changes that the user might want to save on exit
unsaved_changes = False

# Conversation title label (shows filename or 'New Conversation')
conv_title = tk.Label(root, text='New Conversation', font=(None, 12, 'bold'))
conv_title.pack(pady=(8,0))

# Read-only chat area
chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=70, height=20)
chat_area.pack(padx=10, pady=6, fill=tk.BOTH, expand=True)
chat_area.config(state=tk.DISABLED)
# Configure tags for colored labels
chat_area.tag_configure('user_label', foreground='#003366', font=(None, 10, 'bold'))
chat_area.tag_configure('assistant_label', foreground='#b30000', font=(None, 10, 'bold'))


# Helpers to update the read-only chat area from code
def append_chat(text: str):
    chat_area.config(state=tk.NORMAL)
    chat_area.insert(tk.END, text)
    chat_area.see(tk.END)
    chat_area.config(state=tk.DISABLED)


# Insert a single labeled message into the chat_area without modifying history, role text is coloured using tags 
# while the rest of the message remains normal (colon omitted for when the AI is still replying)
def insert_labeled_message(role: str, message: str, ts: str = '', prefix_colon: bool = True):
    chat_area.config(state=tk.NORMAL)
    # choose tag for role
    tag = 'user_label' if role == 'You' else 'assistant_label'
    # insert role with tag
    chat_area.insert(tk.END, role, tag)
    # insert timestamp and rest; optionally include colon separator
    ts_text = f" [{ts}]" if (ts and show_timestamps_var.get()) else ''
    sep = ': ' if prefix_colon else ' '
    chat_area.insert(tk.END, f"{ts_text}{sep}{message}\n\n")
    # extra spacer for assistant replies
    if role != 'You':
        chat_area.insert(tk.END, "\n")
    chat_area.see(tk.END)
    chat_area.config(state=tk.DISABLED)

# Helper for displaying chat history in text box
def render_history():
    chat_area.config(state=tk.NORMAL)
    chat_area.delete(1.0, tk.END)
    # Show the full, untrimmed conversation to the user (full_history)
    # `history` remains the trimmed list used for model context
    for entry_item in full_history:
        if len(entry_item) >= 3:
            role, msg, ts = entry_item[0], entry_item[1], entry_item[2]
        elif len(entry_item) == 2:
            role, msg = entry_item[0], entry_item[1]
            ts = ''
        else:
            continue
        # Respect the show_timestamps_var toggle (hide timestamps when unchecked)
        try:
            show_ts = show_timestamps_var.get()
        except Exception:
            show_ts = True
        # Use the labeled insertion helper so role labels are colored
        try:
            insert_labeled_message(role, msg, ts)
        except Exception:
            # fallback to plain insertion
            ts_text = f" [{ts}]" if (ts and show_ts) else ''
            chat_area.insert(tk.END, f"{role}{ts_text}: {msg}\n\n")
    chat_area.see(tk.END)
    chat_area.config(state=tk.DISABLED)

entry_frame = tk.Frame(root)
entry_frame.pack(fill=tk.X, padx=10, pady=(0,10))

entry = tk.Entry(entry_frame, font=("Arial", 12))
entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
entry.bind("<Return>", lambda e: send_message())

    # Clear Prefs was moved to the Settings menu

send_btn = tk.Button(entry_frame, text="Send", command=send_message, 
                     font=("Arial", 12), bg="lightblue")
send_btn.pack(side=tk.RIGHT)

# Personality variables (used by the separate Personality window)
friendliness_var = tk.IntVar(value=2)
professionalism_var = tk.IntVar(value=1)
profanity_var = tk.IntVar(value=0)
age_var = tk.IntVar(value=30)
gender_var = tk.IntVar(value=1)
humor_var = tk.IntVar(value=0)
sarcasm_var = tk.IntVar(value=0)
introversion_var = tk.IntVar(value=1)

# On startup, attempt to apply the last selected preset stored in presets.json
try:
    presets_path = os.path.join(os.path.dirname(__file__), 'presets.json')
    # personalities/ is where per-file presets are stored (not 'presets/')
    presets_dir = os.path.join(os.path.dirname(__file__), 'personalities')
    last_selected = None
    if os.path.exists(presets_path):
        try:
            with open(presets_path, 'r', encoding='utf-8') as pf:
                loaded = json.load(pf)
            last_selected = loaded.get('last_selected') if isinstance(loaded, dict) else None
        except Exception:
            last_selected = None

    # Only apply if last_selected is a built-in preset or a file in personalities/
    if last_selected:
        applied = False
        if last_selected in DEFAULT_PRESETS:
            vals = DEFAULT_PRESETS[last_selected]
            friendliness_var.set(vals[0])
            professionalism_var.set(vals[1])
            profanity_var.set(vals[2])
            age_var.set(vals[3])
            gender_var.set(vals[4])
            humor_var.set(vals[5])
            sarcasm_var.set(vals[6])
            introversion_var.set(vals[7])
            applied = True
        else:
            # check personalities/ for a matching file
            try:
                fn = os.path.join(presets_dir, f"{last_selected}.json")
                if os.path.exists(fn):
                    with open(fn, 'r', encoding='utf-8') as pf:
                        loaded = json.load(pf)
                    vals = None
                    if isinstance(loaded, list):
                        vals = loaded
                    elif isinstance(loaded, dict) and 'values' in loaded:
                        vals = loaded.get('values')
                    if vals and len(vals) >= 8:
                        vals = [int(x) for x in vals[:8]]
                        friendliness_var.set(vals[0])
                        professionalism_var.set(vals[1])
                        profanity_var.set(vals[2])
                        age_var.set(vals[3])
                        gender_var.set(vals[4])
                        humor_var.set(vals[5])
                        sarcasm_var.set(vals[6])
                        introversion_var.set(vals[7])
                        applied = True
            except Exception:
                applied = False
            # If last_selected was 'Custom' or not found, revert to DEFAULT_PRESETS['Default AI']
            if not last_selected or not applied:
                vals = DEFAULT_PRESETS.get('Default AI')
                friendliness_var.set(vals[0])
                professionalism_var.set(vals[1])
                profanity_var.set(vals[2])
                age_var.set(vals[3])
                gender_var.set(vals[4])
                humor_var.set(vals[5])
                sarcasm_var.set(vals[6])
                introversion_var.set(vals[7])
            # If a saved preset was applied, the UI will be refreshed later after
            # summary/title helper functions are defined
            # Avoid calling them here to prevent editor/static-analysis 'not defined' warnings
except Exception:
    pass

# Show timestamps toggle
show_timestamps_var = tk.BooleanVar(value=False)

# Live summary label in main UI (updated by personality window)
# Make it small, italic and grey so it's less visually aggressive
summary_label = tk.Label(root, text="", wraplength=400, justify='left', font=(None, 9, 'italic'), fg='gray40')
summary_label.pack(padx=8, pady=(4,6))

# (update_summary will be called after its definition so the label reflects startup presets)

# Toggle to show/hide timestamps in the chat display
show_ts_cb = tk.Checkbutton(root, text='Show timestamps', variable=show_timestamps_var, command=render_history)
show_ts_cb.pack(padx=8, pady=(0,6), anchor='w')

# NOTE: Startup prompts are performed after we load persisted settings below
# so they honor the user's stored choice of local vs server mode, the
# prompt_for_api_key() call used to run here before settings were
# applied which could cause it to be skipped or run at the wrong time

# Load persisted settings (use_local_ai) and expose a Tk var for menu toggling
try:
    _loaded_settings = load_settings()
    # If use_local_var already exists (created earlier for the settings menu), reuse it
    if 'use_local_var' in globals() and isinstance(use_local_var, tk.BooleanVar):
        try:
            use_local_var.set(bool(_loaded_settings.get('use_local_ai', True)))
        except Exception:
            pass
    else:
        use_local_var = tk.BooleanVar(value=bool(_loaded_settings.get('use_local_ai', True)))
except Exception:
    if 'use_local_var' in globals() and isinstance(use_local_var, tk.BooleanVar):
        try:
            use_local_var.set(True)
        except Exception:
            pass
    else:
        use_local_var = tk.BooleanVar(value=True)

# Initialize runtime history & preference limits from settings (clamp to reasonable bounds)
try:
    _hist_val = None
    try:
        _hist_val = int(_loaded_settings.get('ai_history_lines')) if isinstance(_loaded_settings, dict) and _loaded_settings.get('ai_history_lines') is not None else None
    except Exception:
        _hist_val = None
    if _hist_val is None:
        HISTORY_LIMIT = 20
    else:
        HISTORY_LIMIT = max(0, min(50, int(_hist_val)))
except Exception:
    HISTORY_LIMIT = 20

try:
    _pref_val = None
    try:
        _pref_val = int(_loaded_settings.get('pref_memory_lines')) if isinstance(_loaded_settings, dict) and _loaded_settings.get('pref_memory_lines') is not None else None
    except Exception:
        _pref_val = None
    if _pref_val is None:
        PREFS_LIMIT = PREFS_DEFAULT_LINES
    else:
        PREFS_LIMIT = max(0, min(50, int(_pref_val)))
except Exception:
    PREFS_LIMIT = PREFS_DEFAULT_LINES

# After loading persisted settings above, prompt for missing credentials
# based on the effective mode (local vs server), then load history
try:
    try:
        # Determine saved credentials and any metadata about deletions
        loaded_meta = load_settings() or {}
        saved_key = get_saved_api_key()
        saved_ep = get_saved_endpoint()

        OPENAI_API_KEY = saved_key  # set global variable for immediate use
        SERVER_ENDPOINT = saved_ep  # set global variable for immediate use

        # If both are missing, prefer prompting for whichever was deleted
        # most recently according to settings.json metadata
        if not saved_key and not saved_ep:
            last = loaded_meta.get('last_credential_deleted') if isinstance(loaded_meta, dict) else None
            if last == 'api_key':
                prompt_for_api_key()
            elif last == 'server_endpoint':
                prompt_for_endpoint()
            else:
                # No metadata: prefer prompting for the client API key by default
                # (users commonly run locally, this avoids defaulting to server mode
                # on fresh installs when no settings.json exists)
                try:
                    prompt_for_api_key()
                except Exception:
                    # If that unexpectedly fails, fall back to endpoint prompt
                    try:
                        prompt_for_endpoint()
                    except Exception:
                        pass
        else:
            # If only one is missing, prompt for that one depending on mode
            if 'use_local_var' in globals() and use_local_var.get():
                if not saved_key:
                    prompt_for_api_key()
            else:
                if not saved_ep:
                    prompt_for_endpoint()
    except Exception:
        pass
    # Load history after any credential dialogs so render_history can include
    # any startup state that the user may have configured in the dialogs
    try:
        load_history()
    except Exception:
        pass
except Exception:
    pass

def update_summary(*args):
    f = friendliness_var.get()
    p = professionalism_var.get()
    r = profanity_var.get()
    a = age_var.get()
    g = gender_var.get()
    h = humor_var.get()
    s = sarcasm_var.get()
    i = introversion_var.get()
    tone = []
    # Friendliness (0-3)
    if f == 3:
        tone.append('very friendly')
    elif f == 2:
        tone.append('friendly')
    elif f == 1:
        tone.append('slightly reserved')
    else:
        tone.append('reserved')

    # Professionalism (0-2)
    if p == 2:
        tone.append('professional')
    elif p == 1:
        tone.append('somewhat professional')
    else:
        tone.append('casual')

    # Profanity (0-2)
    if r == 2:
        tone.append('uses profanity')
    elif r == 1:
        tone.append('occasionally coarse')
    else:
        tone.append('clean language')

    # Humor (0-2)
    if h == 2:
        tone.append('very humorous')
    elif h == 1:
        tone.append('light humour')
    else:
        tone.append('no humour')

    # Sarcasm (0-2)
    if s == 2:
        tone.append('strong sarcasm')
    elif s == 1:
        tone.append('mild sarcasm')
    else:
        tone.append('no sarcasm')

    # Extroversion (0-2)
    if i == 2:
        tone.append('extroverted')
    elif i == 1:
        tone.append('neutral extroversion')
    else:
        tone.append('introverted')

    age_desc = f'age {a}'
    gender_desc = 'feminine' if g==2 else ('masculine' if g==0 else 'gender neutral')
    summary_label.config(text='Summary: ' + ', '.join(tone) + f', {age_desc}, {gender_desc}')
    # After updating summary, also refresh conversation title to show active preset
    try:
        # Determine active preset name and refresh title with it
        preset_name = determine_active_preset_name()
        # preserve current conversation filename if any
        try:
            cur = os.path.basename(current_conversation_path) if current_conversation_path else None
        except Exception:
            cur = None
        set_conversation_title(cur)
    except Exception:
        pass

# Now that update_summary is defined, refresh the summary_label to match startup-applied preset
try:
    update_summary()
except Exception:
    pass


def set_conversation_title(name: str, preset_override: str = None):
    # If the name looks like a filename, strip the .json extension for display
    # Use preset_override if provided, otherwise compute active preset
    try:
        if preset_override:
            preset_label = preset_override
        else:
            preset_label = determine_active_preset_name()
    except Exception:
        preset_label = None

    if name:
        base = os.path.splitext(name)[0]
        display = base if base else 'New Conversation'
    else:
        display = 'New Conversation'

    if preset_label:
        conv_title.config(text=f"{display} (with {preset_label})")
    else:
        conv_title.config(text=display)

# Return the name of the matching preset for current slider values, or 'Custom'
def determine_active_preset_name():    
    # Build the current tuple
    tpl = (
        int(friendliness_var.get()), int(professionalism_var.get()), int(profanity_var.get()),
        int(age_var.get()), int(gender_var.get()), int(humor_var.get()), int(sarcasm_var.get()), int(introversion_var.get())
    )
    # Check built-ins first
    for name, vals in DEFAULT_PRESETS.items():
        if tuple(vals) == tpl:
            return name
    # Check personalities dir for saved presets
    try:
        presets_dir = os.path.join(os.path.dirname(__file__), 'personalities')
        for fname in os.listdir(presets_dir):
            if not fname.lower().endswith('.json'):
                continue
            full = os.path.join(presets_dir, fname)
            try:
                with open(full, 'r', encoding='utf-8') as pf:
                    loaded = json.load(pf)
                vals = None
                if isinstance(loaded, list):
                    vals = loaded
                elif isinstance(loaded, dict) and 'values' in loaded:
                    vals = loaded.get('values')
                if vals and len(vals) >= 8 and tuple(int(x) for x in vals[:8]) == tpl:
                    return os.path.splitext(fname)[0]
            except Exception:
                continue
    except Exception:
        pass
    return 'Custom'

# On startup, show the last-selected preset in the conversation title (if available)
try:
    presets_path = os.path.join(os.path.dirname(__file__), 'presets.json')
    if os.path.exists(presets_path):
        try:
            with open(presets_path, 'r', encoding='utf-8') as pf:
                loaded = json.load(pf)
            last_sel = loaded.get('last_selected') if isinstance(loaded, dict) else None
        except Exception:
            last_sel = None
    else:
        last_sel = None
    if last_sel:
        try:
            set_conversation_title(None, last_sel)
        except Exception:
            pass
except Exception:
    pass

# After a short delay, ask the user if they'd like to load a conversation from disk
def prompt_load_on_startup():
    try:
        conv_dir = os.path.join(os.path.dirname(__file__), 'conversations')
        os.makedirs(conv_dir, exist_ok=True)
    except Exception:
        conv_dir = None
    try:
        # Only prompt if the conversations/ folder contains at least one file
        should_prompt = False
        if conv_dir and os.path.isdir(conv_dir):
            try:
                items = [f for f in os.listdir(conv_dir) if os.path.isfile(os.path.join(conv_dir, f))]
                should_prompt = len(items) > 0
            except Exception:
                should_prompt = False
        if should_prompt:
            if messagebox.askyesno('Load conversation', 'Load an existing conversation from disk?'):
                load_conversation_file()
    except Exception:
        pass

# Schedule prompt shortly after mainloop starts so dialogs are shown properly
try:
    root.after(200, prompt_load_on_startup)
except Exception:
    pass

root.mainloop()