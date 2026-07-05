import tkinter as tk

from tkinter import messagebox


from app.research_ui import ResearchWindow

from app.assessment_ui import AssessmentWindow

from app.clinical_history_ui import (
    ClinicalHistoryWindow
)

from app.window_nav import open_child_window


root = tk.Tk()

root.title("ARCxSpeech")

root.geometry("400x300")



def open_clinical_history():

    open_child_window(root, ClinicalHistoryWindow)


def open_assessment():

    open_child_window(root, AssessmentWindow)


def open_research():

    open_child_window(root, ResearchWindow)


def on_root_closing():
    child = getattr(root, "_active_child", None)
    child_open = child is not None and child.winfo_exists()

    if child_open:
        confirm = messagebox.askyesno(
            "Close ARCxSpeech?",
            "A window is currently open (Assessment / History / R&D). "
            "Closing the dashboard will close it too and any unsaved "
            "work will be lost.\n\n"
            "Are you sure you want to quit?"
        )

        if not confirm:
            return

    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_root_closing)







title = tk.Label(
    root,
    text="ARCxSpeech Dashboard",
    font=("Arial", 18, "bold")
)

title.pack(pady=30)

assessment_btn = tk.Button(
    root,
    text="Open Clinical Assessment",
    command=open_assessment,
    width=25,
    height=2
)

assessment_btn.pack(pady=15)


clinical_history_btn = tk.Button(

    root,

    text="Open Clinical History",

    command=open_clinical_history,

    width=25,

    height=2

)

clinical_history_btn.pack(
    pady=15
)



research_btn = tk.Button(
    root,
    text="Open R&D Mode",
    command=open_research,
    width=25,
    height=2
)

research_btn.pack(pady=15)

root.mainloop()