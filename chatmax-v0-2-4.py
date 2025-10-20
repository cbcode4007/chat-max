# File:        chatmax-v0-2-4.py
# Author:      Colin Bond
# Version:     0.2.4 (2023-10-20, added the ability for the user to hide timestamps in the chat display and show them again)
#
# Description: A simple chat interface for configuring and interacting with 
#              personalized, learning GPT models from an endpoint.

import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
import requests
import json
import threading
import time
import os

# Preferences file path and limits
PREFS_PATH = os.path.join(os.path.dirname(__file__), 'preferences.txt')
PREFS_MAX_CHARS = 2000

endpoint = 'http://192.168.123.128:5001/chat'

def send_message():
    message = entry.get()
    if not message.strip():
        return

    # Add to history (keep last 10 messages). Each entry is (role, message, iso_timestamp)
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    history.append(("You", message, ts))
    if len(history) > 10:
        history.pop(0)

    # Convert GUI history to ChatGPT format WITH system role
    # Start with a neutral, blank-slate system instruction. All tone/style should be provided
    # by subsequent system messages (e.g., personality_instruction and preferences).
    messages_for_gpt = [{"role": "system", "content": (
        "You are a concise chat partner. Do not assume or apply any particular personality or tone, besides keeping concise. Follow any additional system instructions that are appended to this conversation to determine tone, style, and behavior. If no further instructions are provided, respond neutrally and helpfully."
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

        # Friendliness (discrete 0-3)
        if f == 3:
            parts.append('Be very friendly and warm.')
        elif f == 2:
            parts.append('Be friendly.')
        elif f == 1:
            parts.append('Be slightly reserved.')
        else:
            parts.append('Be very reserved and concise.')

        # Professionalism (discrete 0-2)
        if p == 2:
            parts.append('Maintain a professional tone.')
        elif p == 1:
            parts.append('Be somewhat professional.')
        else:
            parts.append('Use casual language.')

        # Profanity (discrete 0-2), but enforce age constraint, young voices should not use profanity
        if a <= 15:
            # force no profanity for young ages
            parts.append('Do not use profanity; avoid coarse language due to youthful voice.')
        else:
            if r == 2:
                parts.append('Profanity allowed: high (may use strong coarse language).')
            elif r == 1:
                parts.append('Profanity allowed: moderate (occasional mild swear words).')
            else:
                parts.append('No profanity; use clean language.')

        # Age
        parts.append(f'Adopt the voice of someone aged {a}.')

        # Gender (discrete 0-2)
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

        # Introversion (0-2): 0=extroverted,1=neutral,2=introverted
        if i == 2:
            parts.append("Favor solitary/quiet hobbies and mention mild nervousness or reserve in social situations when relevant. Do not be excitable, for instance lay off of exclamation marks unless absolutely necessary.")
        elif i == 1:
            parts.append('No particular bias toward introversion or extroversion.')
        else:
            parts.append('Favor social/outgoing hobbies and confident wording. Be excitable and enthusiastic where appropriate, expressing with exclamation marks more often than not.')

        return ' '.join(parts)

    personality_instruction = build_personality_instructions()
    if personality_instruction:
        messages_for_gpt.append({"role": "system", "content": personality_instruction})

    # If a preferences.txt file exists next to this script, append its contents as an additional system message.
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
        # Ignore preference-load errors; do not change payload if reading fails
        pass
    for entry_item in history:
        # backward-compat: entry_item may be (role, msg) or (role, msg, ts)
        if len(entry_item) >= 2:
            role = entry_item[0]
            msg = entry_item[1]
            messages_for_gpt.append({"role": "user" if role == "You" else "assistant", "content": msg})

    # Add user message to chat UI immediately (include timestamp if enabled) and insert AI placeholder
    try:
        if show_timestamps_var.get():
            append_chat(f"You [{ts}]: {message}\n\n")
        else:
            append_chat(f"You: {message}\n\n")
    except Exception:
        # Fallback for older runtime states where the timestamp toggle may not exist
        append_chat(f"You [{ts}]: {message}\n\n")
    append_chat(f"AI is typing...\n\n")
    entry.delete(0, tk.END)
    chat_area.see(tk.END)

    # Disable send controls while awaiting a reply
    send_btn.config(state=tk.DISABLED)
    entry.config(state=tk.DISABLED)
    try:
        show_ts_cb.config(state=tk.DISABLED)
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

                # Build a prompt to extract concise preference lines from the USER's messages only.
                gen_msgs = [
                    {"role": "system", "content": (
                        "Extract concise user preference statements from the conversation. "
                        "Important: consider ONLY the user's messages; ignore all assistant/AI utterances. "
                        "Output plain text only, one canonical statement per line, using this exact pattern: The user's <property> is <value>. "
                        "Examples: The user's favourite colour is purple; The user's name is Colin. "
                        "Do NOT include numbering, explanations, or extra commentary. Compare with the existing preferences below and output ONLY NEW or UPDATED preference lines (one per line). If there are none, output nothing."
                    )},
                ]

                # Include existing preferences as context
                if current_prefs:
                    gen_msgs.append({"role": "system", "content": "Existing preferences:\n" + current_prefs})

                # Provide recent user-only history as context (limit to last 8 user messages)
                # history entries may be (role, msg, ts) so don't unpack incorrectly
                user_msgs = [item[1] for item in history if isinstance(item, (list, tuple)) and len(item) >= 2 and item[0] == "You"]
                for um in user_msgs[-8:]:
                    gen_msgs.append({"role": "user", "content": um})

                # Also include the current user message explicitly
                gen_msgs.append({"role": "user", "content": message})

                # Try to get extracted preferences from the server
                try:
                    gen_resp = requests.post(endpoint, json={'messages': gen_msgs}, timeout=20)
                    gen_resp.raise_for_status()
                    gen_data = gen_resp.json()
                    extracted = gen_data.get('response', '').strip() if isinstance(gen_data, dict) else ''
                except Exception as e:
                    extracted = ''

                if extracted:
                    # Parse lines and merge with current_prefs (replace by key before ' is ' if present)
                    new_lines = [l.strip() for l in extracted.splitlines() if l.strip()]
                    existing_lines = [l.strip() for l in (current_prefs.splitlines() if current_prefs else []) if l.strip()]

                    def pref_key(line):
                        low = line.lower()
                        if ' is ' in low:
                            return low.split(' is ', 1)[0].strip()
                        return low

                    for nl in new_lines:
                        k = pref_key(nl)
                        # build a map of existing preferences keyed by canonical key
                        # so updates replace the correct entry without accidental collisions
                        existing_map = {}
                        for ex in existing_lines:
                            existing_map[pref_key(ex)] = ex

                        existing_map[k] = nl

                        # Rebuild existing_lines preserving insertion order (new/updated at end if new)
                        existing_lines = list(existing_map.values())

                    # Join and truncate to PREFS_MAX_CHARS
                    merged = '\n'.join(existing_lines).strip()
                    print('[prefs] merged preferences:', repr(merged))
                    if len(merged) > PREFS_MAX_CHARS:
                        merged = merged[:PREFS_MAX_CHARS]
                    try:
                        # Write atomically: write to a temp file then replace
                        tmp_path = PREFS_PATH + '.tmp'
                        with open(tmp_path, 'w', encoding='utf-8') as pf:
                            pf.write(merged)
                            pf.flush()
                            try:
                                os.fsync(pf.fileno())
                            except Exception:
                                pass
                        os.replace(tmp_path, PREFS_PATH)
                        print(f"[prefs] wrote merged preferences to {PREFS_PATH}")
                    except Exception as e:
                        print(f"[prefs] failed to write preferences: {e}")
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

            # Send user message to AI endpoint with personalized (pref and memory) payload
            response = requests.post(endpoint, json={'messages': payload}, timeout=30)
            response.raise_for_status()
            data = response.json()
            ai_reply = data.get('response', '')

            # Update history (append AI reply)
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            history.append(("AI", ai_reply, ts))
            if len(history) > 10:
                history.pop(0)

            # Schedule UI update on main thread: replace the last AI placeholder with real reply
            def on_success():
                # Re-render the chat_area from history to keep it simple and robust
                render_history()
                send_btn.config(state=tk.NORMAL)
                entry.config(state=tk.NORMAL)
                try:
                    show_ts_cb.config(state=tk.NORMAL)
                except Exception:
                    pass

            root.after(0, on_success)
        except Exception as e:
            err_text = f"Error: {str(e)}"

            # Append an error entry to history
            ts = time.strftime('%Y-%m-%d %H:%M:%S')
            history.append(("AI", err_text, ts))
            if len(history) > 10:
                history.pop(0)

            def on_error():
                render_history()
                send_btn.config(state=tk.NORMAL)
                entry.config(state=tk.NORMAL)
                try:
                    show_ts_cb.config(state=tk.NORMAL)
                except Exception:
                    pass

            root.after(0, on_error)

    # Start background thread for the request
    thread = threading.Thread(target=worker, args=(messages_for_gpt,), daemon=True)
    thread.start()

def load_history():
    # Use the central render function which handles enabling/disabling the widget
    render_history()


def new_conversation():
    if messagebox.askyesno("New Conversation", "Start a new conversation? This will clear the current chat history."):
        history.clear()
        # Re-render (will clear the display and keep widget state consistent)
        render_history()
        set_conversation_title('New Conversation')


def save_conversation():
    path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files','*.json'), ('All files','*.*')])
    if not path:
        return
    try:
        # Save history, ensure entries are serializable lists
        serial = []
        for item in history:
            if isinstance(item, (list, tuple)):
                serial.append(list(item))
            else:
                serial.append([str(item)])
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(serial, f, ensure_ascii=False, indent=2)
        messagebox.showinfo('Saved', f'Conversation saved to {path}')
    except Exception as e:
        messagebox.showerror('Save error', str(e))


def load_conversation_file():
    path = filedialog.askopenfilename(filetypes=[('JSON files','*.json'), ('All files','*.*')])
    if not path:
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Expecting a list of [role, message] pairs
        if isinstance(data, list):
            history.clear()
            for item in data:
                # item may be [role, message] or [role, message, timestamp]
                if isinstance(item, list) or isinstance(item, tuple):
                    if len(item) >= 2:
                        role = item[0]
                        msg = item[1]
                        ts = item[2] if len(item) > 2 else time.strftime('%Y-%m-%d %H:%M:%S')
                        history.append((role, msg, ts))
            render_history()
            set_conversation_title(os.path.basename(path))
            messagebox.showinfo('Loaded', f'Conversation loaded from {path}')
    except Exception as e:
        messagebox.showerror('Load error', str(e))


def clear_prefs():
    try:
        if os.path.exists(PREFS_PATH):
            os.remove(PREFS_PATH)
            messagebox.showinfo('Preferences cleared', 'preferences.txt deleted')
        else:
            messagebox.showinfo('Preferences', 'No preferences file to delete')
    except Exception as e:
        messagebox.showerror('Error', str(e))

# GUI Setup
root = tk.Tk()
root.title("Chat Test")
root.geometry("800x600")

# Menu bar
menubar = tk.Menu(root)
file_menu = tk.Menu(menubar, tearoff=0)
file_menu.add_command(label='New', command=new_conversation)
file_menu.add_command(label='Save', command=save_conversation)
file_menu.add_command(label='Load', command=load_conversation_file)
file_menu.add_separator()
file_menu.add_command(label='Exit', command=root.quit)
menubar.add_cascade(label='File', menu=file_menu)
root.config(menu=menubar)

# Add Personality menu entry (opens a separate window)
def open_personality_window():
    # Reuse global vars and build a Toplevel window with sliders
    if getattr(open_personality_window, 'win', None) and open_personality_window.win.winfo_exists():
        open_personality_window.win.lift()
        return
    win = tk.Toplevel(root)
    win.title('Personality')
    # Do not hardcode geometry so the window can adapt to scaling, but with a reasonable minimum
    win.minsize(320, 300)
    open_personality_window.win = win

    tk.Label(win, text='Personality', font=(None, 12, 'bold')).pack(pady=(6,4))

    # Presets map: name -> tuple of slider values
    presets = {
        'Default AI': (2, 1, 0, 30, 1, 0, 0, 1),
        'Helpful Professional': (2, 2, 0, 35, 1, 0, 0, 1),
        'Casual Friendly': (3, 0, 0, 25, 1, 1, 0, 0),
        'Playful Sarcastic': (2, 0, 1, 18, 1, 2, 2, 1),
        'Child-Friendly': (3, 1, 0, 12, 1, 0, 0, 1),
        'Stoic Professional': (1, 2, 0, 40, 1, 0, 0, 2),
        'Sailor-Mouth': (0, 0, 2, 30, 1, 1, 2, 2),
    }

    # Try to load user presets and last selection from presets.json (next to script)
    presets_path = os.path.join(os.path.dirname(__file__), 'presets.json')
    try:
        if os.path.exists(presets_path):
            with open(presets_path, 'r', encoding='utf-8') as pf:
                loaded = json.load(pf)
            file_presets = loaded.get('presets', {}) if isinstance(loaded, dict) else {}
            for k, v in file_presets.items():
                # Ensure stored values are tuples of ints
                try:
                    presets[k] = tuple(int(x) for x in v)
                except Exception:
                    pass
            last_selected = loaded.get('last_selected') if isinstance(loaded, dict) else None
        else:
            last_selected = None
    except Exception:
        last_selected = None

    # We'll include a 'Custom' label for when slider values don't match any preset
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
    # OptionMenu options: show 'Custom' plus all preset names
    option_names = ['Custom'] + list(presets.keys())
    tk.OptionMenu(win, preset_var, *option_names, command=apply_preset).pack(fill=tk.X, padx=8)

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

    # Called when a Scale is manipulated by the user. Update summary and preset selector.
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

    tk.Label(win, text='Friendliness (0=reserved,1=slightly,2=friendly,3=very)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=3, orient=tk.HORIZONTAL, variable=friendliness_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Professionalism (0=casual,1=somewhat,2=professional)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=professionalism_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Profanity (0=clean,1=moderate,2=high)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=profanity_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Age').pack(anchor='w', padx=8)
    tk.Scale(win, from_=5, to=127, orient=tk.HORIZONTAL, variable=age_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Gender (0=masculine,1=neutral,2=feminine)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=gender_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Humour (0=none,1=light,2=high)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=humor_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Sarcasm (0=none,1=mild,2=strong)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=sarcasm_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Introversion (0=extroverted,1=neutral,2=introverted)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=introversion_var, command=on_slider_change).pack(fill=tk.X, padx=8)

    # Summary shown in the window too (wraplength will be updated on resize)
    win_summary = tk.Label(win, text='', wraplength=280, justify='left')
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

    # If last_selected was saved and exists, keep it; otherwise try to match current sliders
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

    # Buttons were intentionally removed to allow immediate application of changes
    # (apply_changes and apply_preset remain available programmatically)

personality_menu = tk.Menu(menubar, tearoff=0)
personality_menu.add_command(label='Configure...', command=open_personality_window)
menubar.add_cascade(label='Personality', menu=personality_menu)

history = []  # Chat history (10 pairs max)

# Conversation title label (shows filename or 'New Conversation')
conv_title = tk.Label(root, text='New Conversation', font=(None, 12, 'bold'))
conv_title.pack(pady=(8,0))

# Read-only chat area
chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=70, height=20)
chat_area.pack(padx=10, pady=6, fill=tk.BOTH, expand=True)
chat_area.config(state=tk.DISABLED)


# Helpers to update the read-only chat area from code
def append_chat(text: str):
    chat_area.config(state=tk.NORMAL)
    chat_area.insert(tk.END, text)
    chat_area.see(tk.END)
    chat_area.config(state=tk.DISABLED)


def render_history():
    chat_area.config(state=tk.NORMAL)
    chat_area.delete(1.0, tk.END)
    for entry_item in history:
        if len(entry_item) >= 3:
            role, msg, ts = entry_item[0], entry_item[1], entry_item[2]
        elif len(entry_item) == 2:
            role, msg = entry_item[0], entry_item[1]
            ts = ''
        else:
            continue
        # Respect the show_timestamps_var toggle (hide timestamps when unchecked).
        try:
            show_ts = show_timestamps_var.get()
        except Exception:
            show_ts = True
        ts_text = f" [{ts}]" if (ts and show_ts) else ''
        chat_area.insert(tk.END, f"{role}{ts_text}: {msg}\n\n")
        if role == "AI":
            chat_area.insert(tk.END, "\n")
    chat_area.see(tk.END)
    chat_area.config(state=tk.DISABLED)

entry_frame = tk.Frame(root)
entry_frame.pack(fill=tk.X, padx=10, pady=(0,10))

entry = tk.Entry(entry_frame, font=("Arial", 12))
entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
entry.bind("<Return>", lambda e: send_message())

clear_prefs_btn = tk.Button(entry_frame, text="Clear Prefs", command=lambda: clear_prefs(), font=("Arial", 10))
clear_prefs_btn.pack(side=tk.RIGHT, padx=(0,6))

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

# Show timestamps toggle
show_timestamps_var = tk.BooleanVar(value=True)

# Live summary label in main UI (updated by personality window)
summary_label = tk.Label(root, text="Summary: friendly, somewhat professional, clean language, no humour, no sarcasm, neutral extroversion, age 30, neutral", wraplength=400, justify='left')
summary_label.pack(padx=8, pady=(4,6))

# Toggle to show/hide timestamps in the chat display
show_ts_cb = tk.Checkbutton(root, text='Show timestamps', variable=show_timestamps_var, command=render_history)
show_ts_cb.pack(padx=8, pady=(0,6), anchor='w')

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
    # Friendliness mapping (0-3)
    if f == 3:
        tone.append('very friendly')
    elif f == 2:
        tone.append('friendly')
    elif f == 1:
        tone.append('slightly reserved')
    else:
        tone.append('reserved')

    # Professionalism mapping (0-2)
    if p == 2:
        tone.append('professional')
    elif p == 1:
        tone.append('somewhat professional')
    else:
        tone.append('casual')

    # Profanity mapping (0-2)
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

    # Introversion (0-2)
    if i == 2:
        tone.append('introverted')
    elif i == 1:
        tone.append('neutral extroversion')
    else:
        tone.append('extroverted')

    age_desc = f'age {a}'
    gender_desc = 'feminine' if g==2 else ('masculine' if g==0 else 'gender neutral')
    summary_label.config(text='Summary: ' + ', '.join(tone) + f', {age_desc}, {gender_desc}')


def set_conversation_title(name: str):
    conv_title.config(text=name if name else 'New Conversation')

# Load history on start
load_history()

root.mainloop()
