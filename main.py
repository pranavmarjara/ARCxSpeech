import tkinter as tk

from tkinter import simpledialog
from tkinter import messagebox

from app.ui import ARCxSpeechUI
from app.history_ui import HistoryWindow


root = tk.Tk()

root.title("ARCxSpeech")

root.geometry("400x300")


def open_analysis():

    analysis_window = tk.Toplevel(root)

    ARCxSpeechUI(analysis_window)


def open_history():

    history_window = tk.Toplevel(root)

    HistoryWindow(history_window)


title = tk.Label(
    root,
    text="ARCxSpeech Dashboard",
    font=("Arial", 18, "bold")
)

title.pack(pady=30)

analysis_btn = tk.Button(
    root,
    text="Open Analysis",
    command=open_analysis,
    width=25,
    height=2
)

analysis_btn.pack(pady=15)

history_btn = tk.Button(
    root,
    text="Open History",
    command=open_history,
    width=25,
    height=2
)

history_btn.pack(pady=15)

root.mainloop()