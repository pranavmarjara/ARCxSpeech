import tkinter as tk

from tkinter import simpledialog
from tkinter import messagebox

from app.ui import ARCxSpeechUI
from app.history_ui import HistoryWindow

from app.research_ui import ResearchWindow

root = tk.Tk()

root.title("ARCxSpeech")

root.geometry("400x300")

def open_research():

    research_window = tk.Toplevel(root)

    ResearchWindow(
        research_window
    )

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

research_btn = tk.Button(
    root,
    text="Open R&D Mode",
    command=open_research,
    width=25,
    height=2
)

research_btn.pack(pady=15)

root.mainloop()