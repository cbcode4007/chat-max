# File:        chatmax-v0-0-1.py
# Author:      Colin Bond
# Version:     0.0.1
# Description: A simple chat interface for interacting with GPT models from an endpoint.

import tkinter as tk
from tkinter import scrolledtext
import requests
import json

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
    for role, msg in history:
        messages_for_gpt.append({"role": "user" if role == "You" else "assistant", "content": msg})
    
    # Add user message to chat
    chat_area.insert(tk.END, f"You: {message}\n")
    entry.delete(0, tk.END)

    print("Payload message sent to server:", messages_for_gpt)
    
    try:
        response = requests.post(endpoint,
                               json={'messages': messages_for_gpt}, timeout=30)
        response.raise_for_status()
        data = response.json()
        ai_reply = data['response']
        
        # Add AI message to history
        history.append(("AI", ai_reply))
        if len(history) > 10:
            history.pop(0)
            
        chat_area.insert(tk.END, f"AI: {ai_reply}\n\n")
    except Exception as e:
        chat_area.insert(tk.END, f"Error: {str(e)}\n\n")
    
    chat_area.see(tk.END)

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
