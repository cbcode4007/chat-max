# File:        chatmax-v0-1-0.py
# Author:      Colin Bond
# Version:     0.1.0 (2023-10-17, added AI user preference extraction to a file for further personalization)
# Description: A simple chat interface for interacting with GPT models from an endpoint.

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

    # Add to history (keep last 10 pairs)
    history.append(("You", message))
    if len(history) > 10:
        history.pop(0)

    # Convert GUI history to ChatGPT format WITH system role
    messages_for_gpt = [{"role": "system", "content": (
        "You are a friendly, concise conversation partner. Reply like a casual human friend: short (1–3 sentences), direct, and occasionally blunt but helpful. "
        "Ask a single clarifying question only when necessary. Match the user's tone, keep answers focused and actionable, and avoid long explanations."
    )}]

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
    for role, msg in history:
        messages_for_gpt.append({"role": "user" if role == "You" else "assistant", "content": msg})

    # Add user message to chat UI immediately and insert AI placeholder
    chat_area.insert(tk.END, f"You: {message}\n")
    chat_area.insert(tk.END, f"AI is typing...\n\n")
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
            history.append(("AI", ai_reply))
            if len(history) > 10:
                history.pop(0)

            # Schedule UI update on main thread: replace the last AI placeholder with real reply
            def on_success():
                # Re-render the chat_area from history to keep it simple and robust
                chat_area.delete(1.0, tk.END)
                for role, msg in history:
                    chat_area.insert(tk.END, f"{role}: {msg}\n")
                    if role == "AI":
                        chat_area.insert(tk.END, "\n")
                chat_area.see(tk.END)
                send_btn.config(state=tk.NORMAL)
                entry.config(state=tk.NORMAL)

            root.after(0, on_success)
        except Exception as e:
            err_text = f"Error: {str(e)}"

            # Append an error entry to history
            history.append(("AI", err_text))
            if len(history) > 10:
                history.pop(0)

            def on_error():
                chat_area.delete(1.0, tk.END)
                for role, msg in history:
                    chat_area.insert(tk.END, f"{role}: {msg}\n")
                    if role == "AI":
                        chat_area.insert(tk.END, "\n")
                chat_area.see(tk.END)
                send_btn.config(state=tk.NORMAL)
                entry.config(state=tk.NORMAL)

            root.after(0, on_error)

    # Start background thread for the request
    thread = threading.Thread(target=worker, args=(messages_for_gpt,), daemon=True)
    thread.start()

def load_history():
    chat_area.delete(1.0, tk.END)
    for role, msg in history:
        chat_area.insert(tk.END, f"{role}: {msg}\n")
        if role == "AI":
            chat_area.insert(tk.END, "\n")
    chat_area.see(tk.END)


def new_conversation():
    if messagebox.askyesno("New Conversation", "Start a new conversation? This will clear the current chat history."):
        history.clear()
        chat_area.delete(1.0, tk.END)


def save_conversation():
    path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files','*.json'), ('All files','*.*')])
    if not path:
        return
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
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
                if isinstance(item, list) or isinstance(item, tuple):
                    if len(item) >= 2:
                        history.append((item[0], item[1]))
            load_history()
            messagebox.showinfo('Loaded', f'Conversation loaded from {path}')
    except Exception as e:
        messagebox.showerror('Load error', str(e))

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

history = []  # Chat history (10 pairs max)

chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=70, height=20)
chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

entry_frame = tk.Frame(root)
entry_frame.pack(fill=tk.X, padx=10, pady=(0,10))

entry = tk.Entry(entry_frame, font=("Arial", 12))
entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
entry.bind("<Return>", lambda e: send_message())

send_btn = tk.Button(entry_frame, text="Send", command=send_message, 
                     font=("Arial", 12), bg="lightblue")
send_btn.pack(side=tk.RIGHT)

# Load history on start
load_history()

root.mainloop()
