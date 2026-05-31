import tkinter as tk

from tkinter import simpledialog
from app.session_store import save_session

from tkinter import ttk
from tkinter import filedialog

from app.feature_extractor import (
    extract_vowel_features,
    extract_ddk_features
)


class ARCxSpeechUI:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "ARCxSpeech Clinical Dashboard"
        )

        self.root.geometry("900x700")

        self.filepath = None

        # -----------------------------
        # TITLE
        # -----------------------------

        title = tk.Label(
            root,
            text="ARCxSpeech Clinical Feature Extraction",
            font=("Arial", 18, "bold")
        )

        title.pack(pady=10)

        # -----------------------------
        # PATIENT NAME
        # -----------------------------

        patient_label = tk.Label(
            root,
            text="Patient Name",
            font=("Arial", 12, "bold")
        )

        patient_label.pack(pady=5)

        self.patient_entry = tk.Entry(
            root,
            width=40
        )

        self.patient_entry.pack(pady=5)


        # -----------------------------
        # AGE
        # -----------------------------

        age_label = tk.Label(
            root,
            text="Age",
            font=("Arial", 12, "bold")
        )

        age_label.pack(pady=5)

        self.age_entry = tk.Entry(
            root,
            width=40
        )

        self.age_entry.pack(pady=5)

        # -----------------------------
        # SEX
        # -----------------------------

        sex_label = tk.Label(
            root,
            text="Sex",
            font=("Arial", 12, "bold")
        )

        sex_label.pack(pady=5)

        self.sex_var = tk.StringVar()

        self.sex_dropdown = ttk.Combobox(
            root,
            textvariable=self.sex_var,
            values=[
                "Male",
                "Female",
                "Other"
            ],
            state="readonly",
            width=37
        )

        self.sex_dropdown.pack(pady=5)


        # -----------------------------
        # TASK TYPE
        # -----------------------------

        task_label = tk.Label(
            root,
            text="Task Type",
            font=("Arial", 12, "bold")
        )

        task_label.pack(pady=5)

        self.task_var = tk.StringVar()

        self.task_dropdown = ttk.Combobox(
            root,
            textvariable=self.task_var,
            values=[
                "Sustained Vowel",
                "DDK"
            ],
            state="readonly",
            width=37
        )

        self.task_dropdown.pack(pady=5)

        # -----------------------------
        # SELECT FILE BUTTON
        # -----------------------------

        select_btn = tk.Button(
            root,
            text="Select WAV File",
            command=self.select_file,
            width=25,
            height=2
        )

        select_btn.pack(pady=10)

        # -----------------------------
        # PROCESS BUTTON
        # -----------------------------

        process_btn = tk.Button(
            root,
            text="Process Audio",
            command=self.process_audio,
            width=25,
            height=2
        )

        process_btn.pack(pady=10)

        # -----------------------------
        # FILE LABEL
        # -----------------------------

        self.file_label = tk.Label(
            root,
            text="No file selected",
            wraplength=800
        )

        self.file_label.pack(pady=10)

        # -----------------------------
        # TABLE
        # -----------------------------

        columns = ("Metric", "Value")

        self.tree = ttk.Treeview(
            root,
            columns=columns,
            show="headings",
            height=25
        )

        self.tree.heading(
            "Metric",
            text="Metric"
        )

        self.tree.heading(
            "Value",
            text="Value"
        )

        self.tree.column(
            "Metric",
            width=350
        )

        self.tree.column(
            "Value",
            width=200
        )

        self.tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20
        )

    # ---------------------------------
    # SELECT FILE
    # ---------------------------------

    def select_file(self):

        self.filepath = filedialog.askopenfilename(
            filetypes=[("WAV files", "*.wav")]
        )

        if self.filepath:

            self.file_label.config(
                text=self.filepath
            )

    # ---------------------------------
    # PROCESS AUDIO
    # ---------------------------------

    def process_audio(self):

        if not self.filepath:
            return


        patient_name = self.patient_entry.get()

        age = self.age_entry.get()

        sex = self.sex_var.get()

        task = self.task_var.get()

        if not patient_name or not age or not sex or not task:
    
            return

        if task == "Sustained Vowel":

            metrics = extract_vowel_features(
                self.filepath
            )

        elif task == "DDK":

            metrics = extract_ddk_features(
                self.filepath
            )

        else:
            return
        patient_name = self.patient_entry.get()

        task = self.task_var.get()

        if not patient_name or not age or not sex or not task:
    
            return

        save_session(
            patient_name,
            age,
            sex,
            task,
            metrics
        )

        # Clear previous rows

        for item in self.tree.get_children():
            self.tree.delete(item)

        # Insert metrics

        for key, value in metrics.items():

            self.tree.insert(
                "",
                "end",
                values=(key, value)
            )