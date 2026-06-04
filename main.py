import tkinter as tk

from tkinter import simpledialog
from tkinter import messagebox


from app.research_ui import ResearchWindow

from app.assessment_ui import AssessmentWindow

from app.clinical_history_ui import (
    ClinicalHistoryWindow
)


root = tk.Tk()

root.title("ARCxSpeech")

root.geometry("400x300")



def open_clinical_history():

    history_window = tk.Toplevel(
        root
    )

    ClinicalHistoryWindow(
        history_window
    )


def open_assessment():

    assessment_window = tk.Toplevel(root)

    AssessmentWindow(
        assessment_window
    )

def open_research():

    research_window = tk.Toplevel(root)

    ResearchWindow(
        research_window
    )







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