import tkinter as tk

from tkinter import ttk
from tkinter import filedialog

from app.feature_extractor import extract_features


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

        metrics = extract_features(
            self.filepath
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