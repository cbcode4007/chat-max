# File:        chatmax-v0-0-3.py
# Author:      Colin Bond
# Version:     0.0.3 (2023-10-16, added user preferences loading from a file for some more personalized responses)
# Description: A simple chat interface for interacting with GPT models from an endpoint.

import tkinter as tk
from tkinter import scrolledtext
import requests
import json
import threading
import time

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
    messages_for_gpt = [{"role": "system", "content": "You are a lively and thoughtful chat partner who enjoys engaging in very casual and concise conversation. You keep your replies short and to the point, with a touch of bluntness, but try to be helpful nonetheless."}]

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

# GUI Setup
root = tk.Tk()
root.title("Chat Test")
root.geometry("800x600")

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
