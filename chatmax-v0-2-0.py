# File:        chatmax-v0-2-0.py
# Author:      Colin Bond
# Version:     0.2.0 (2023-10-17, added configurable personality settings)
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
        f = friendliness_var.get()
        p = professionalism_var.get()
        r = profanity_var.get()
        a = age_var.get()
        g = gender_var.get()

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

        # Profanity (discrete 0-2)
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
    except Exception:
        # Ignore preference-load errors; do not change payload if reading fails
        pass
    for entry_item in history:
        # backward-compat: entry_item may be (role, msg) or (role, msg, ts)
        if len(entry_item) >= 2:
            role = entry_item[0]
            msg = entry_item[1]
            messages_for_gpt.append({"role": "user" if role == "You" else "assistant", "content": msg})

    # Add user message to chat UI immediately and insert AI placeholder
    append_chat(f"You: {message}\n")
    append_chat(f"AI is typing...\n\n")
    entry.delete(0, tk.END)
    chat_area.see(tk.END)

    # Disable send controls while awaiting a reply
    send_btn.config(state=tk.DISABLED)
    entry.config(state=tk.DISABLED)

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

                # Provide recent USER-only history as context (limit to last 8 user messages)
                user_msgs = [msg for role, msg in history if role == "You"]
                for um in user_msgs[-8:]:
                    gen_msgs.append({"role": "user", "content": um})

                # Also include the current user message explicitly
                gen_msgs.append({"role": "user", "content": message})

                print("Requesting extracted preferences from server")
                gen_resp = requests.post(endpoint, json={'messages': gen_msgs}, timeout=20)
                gen_resp.raise_for_status()
                gen_data = gen_resp.json()
                extracted = gen_data.get('response', '').strip()

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
                        replaced = False
                        for i, ex in enumerate(existing_lines):
                            if pref_key(ex) == k:
                                existing_lines[i] = nl
                                replaced = True
                                break
                        if not replaced:
                            existing_lines.append(nl)

                    # Join and truncate to PREFS_MAX_CHARS
                    merged = '\n'.join(existing_lines).strip()
                    if len(merged) > PREFS_MAX_CHARS:
                        merged = merged[:PREFS_MAX_CHARS]
                    try:
                        with open(PREFS_PATH, 'w', encoding='utf-8') as pf:
                            pf.write(merged)
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

            print("Payload message sent to server:", payload)
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
        # Save history; ensure entries are serializable lists
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
    # Do not hardcode geometry so the window can adapt to scaling; set a reasonable minimum
    win.minsize(320, 300)
    open_personality_window.win = win

    tk.Label(win, text='Personality', font=(None, 12, 'bold')).pack(pady=(6,4))

    tk.Label(win, text='Friendliness (0=reserved, 1=slightly, 2=friendly, 3=very)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=3, orient=tk.HORIZONTAL, variable=friendliness_var).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Professionalism (0=casual,1=somewhat,2=professional)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=professionalism_var).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Profanity (0=clean,1=moderate,2=high)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=profanity_var).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Age').pack(anchor='w', padx=8)
    tk.Scale(win, from_=13, to=90, orient=tk.HORIZONTAL, variable=age_var).pack(fill=tk.X, padx=8)

    tk.Label(win, text='Gender (0=masculine,1=neutral,2=feminine)').pack(anchor='w', padx=8)
    tk.Scale(win, from_=0, to=2, orient=tk.HORIZONTAL, variable=gender_var).pack(fill=tk.X, padx=8)

    # Summary shown in the window too (wraplength will be updated on resize)
    win_summary = tk.Label(win, text='', wraplength=280, justify='left')
    win_summary.pack(padx=8, pady=10, fill=tk.X)

    # Update the shared summary label and the local window label
    def update_both(*args):
        update_summary()
        if win_summary:
            win_summary.config(text=summary_label.cget('text'))

    # Register traces once so update_both runs when any var changes
    for var in (friendliness_var, professionalism_var, profanity_var, age_var, gender_var):
        var.trace_add('write', update_both)

    # Initialize window summary
    win_summary.config(text=summary_label.cget('text'))

    # Make the summary wrap adaptively when the Toplevel is resized
    def on_win_configure(event):
        # leave some padding (16px each side)
        new_wrap = max(100, event.width - 32)
        win_summary.config(wraplength=new_wrap)

    win.bind('<Configure>', on_win_configure)

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
        ts_text = f" [{ts}]" if ts else ''
        chat_area.insert(tk.END, f"{role}{ts_text}: {msg}\n")
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

# Live summary label in main UI (updated by personality window)
summary_label = tk.Label(root, text="Summary: Friendly, casual", wraplength=400, justify='left')
summary_label.pack(padx=8, pady=(4,6))

def update_summary(*args):
    f = friendliness_var.get()
    p = professionalism_var.get()
    r = profanity_var.get()
    a = age_var.get()
    g = gender_var.get()
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

    age_desc = f'age {a}'
    gender_desc = 'feminine' if g==2 else ('masculine' if g==0 else 'neutral')
    summary_label.config(text='Summary: ' + ', '.join(tone) + f', {age_desc}, {gender_desc}')


def set_conversation_title(name: str):
    conv_title.config(text=name if name else 'New Conversation')

# Load history on start
load_history()

root.mainloop()
