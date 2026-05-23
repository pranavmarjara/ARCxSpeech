import tkinter as tk

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

from app.feature_extractor import (
    extract_vowel_features,
    extract_ddk_features
)

from app.research_store import (
    save_batch,
    load_research_data
)

from app.research_history_ui import (
    ResearchHistoryWindow
)

class ResearchWindow:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "ARCxSpeech R&D Mode"
        )

        self.root.geometry("1000x700")

        self.filepaths = []

        # -------------------------
        # TITLE
        # -------------------------

        title = tk.Label(
            root,
            text="R&D Batch Testing",
            font=("Arial", 18, "bold")
        )

        title.pack(pady=10)

        # -------------------------
        # BATCH NAME
        # -------------------------

        tk.Label(
            root,
            text="Batch Name"
        ).pack()

        self.batch_entry = tk.Entry(
            root,
            width=40
        )

        self.batch_entry.pack(pady=5)

        # -------------------------
        # TASK
        # -------------------------

        tk.Label(
            root,
            text="Task"
        ).pack()

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

        # -------------------------
        # BULK UPLOAD
        # -------------------------

        upload_btn = tk.Button(
            root,
            text="Bulk Upload upto 50 WAVs",
            command=self.bulk_upload,
            width=25,
            height=2
        )

        upload_btn.pack(pady=10)

        # -------------------------
        # PROCESS
        # -------------------------

        process_btn = tk.Button(
            root,
            text="Process Batch",
            command=self.process_batch,
            width=25,
            height=2
        )

        process_btn.pack(pady=10)

        # -------------------------
        # HISTORY BUTTON
        # -------------------------

        history_btn = tk.Button(
            root,
            text="Open R&D History",
            command=self.open_history,
            width=25,
            height=2
        )

        history_btn.pack(pady=10)

        # -------------------------
        # FILE LIST
        # -------------------------

        self.file_list = tk.Listbox(
            root,
            width=100,
            height=10
        )

        self.file_list.pack(pady=10)

        # -------------------------
        # INDIVIDUAL AUDIO TABLE
        # -------------------------

        individual_label = tk.Label(
            root,
            text="Individual Audio Metrics",
            font=("Arial", 14, "bold")
        )

        individual_label.pack(pady=10)

        self.individual_tree = ttk.Treeview(
            root,
            show="headings",
            height=10
        )

        self.individual_tree.pack(
            fill="x",
            padx=20,
            pady=10
        )

        # -------------------------
        # AGGREGATE TABLE
        # -------------------------

        aggregate_label = tk.Label(
            root,
            text="Aggregate Statistics",
            font=("Arial", 14, "bold")
        )

        aggregate_label.pack(pady=10)

        columns = (
            "Metric",
            "Mean",
            "Median",
            "Mode",
            "Std Dev"
        )

        self.tree = ttk.Treeview(
            root,
            columns=columns,
            show="headings",
            height=15
        )

        for col in columns:

            self.tree.heading(
                col,
                text=col
            )

            self.tree.column(
                col,
                width=150
            )

        self.tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20
        )

    # ---------------------------------
    # BULK UPLOAD
    # ---------------------------------

    def bulk_upload(self):

        self.filepaths = filedialog.askopenfilenames(
            filetypes=[
                ("WAV files", "*.wav")
            ]
        )

        self.file_list.delete(
            0,
            tk.END
        )

        for file in self.filepaths:

            self.file_list.insert(
                tk.END,
                file
            )


    # ---------------------------------
    # OPEN HISTORY
    # ---------------------------------

    def open_history(self):

        history_window = tk.Toplevel(
            self.root
        )

        ResearchHistoryWindow(
            history_window
        )

    # ---------------------------------
    # PROCESS BATCH
    # ---------------------------------

    def process_batch(self):

        batch_name = self.batch_entry.get()

        task = self.task_var.get()

        if not batch_name or not task:

            messagebox.showerror(
                "Error",
                "Enter batch name and task."
            )

            return

        file_count = len(self.filepaths)

        if file_count < 1:

            messagebox.showerror(
                "Error",
                "Upload at least 1 WAV file."
            )

            return

        if file_count > 50:

            messagebox.showerror(
                "Error",
                "Maximum batch size is 50 WAV files."
            )

            return

        all_metrics = []

        recordings = []

        for filepath in self.filepaths:

            if task == "Sustained Vowel":

                metrics = extract_vowel_features(
                    filepath
                )

            else:

                metrics = extract_ddk_features(
                    filepath
                )

            feature_vector = []

            for value in metrics.values():

                if isinstance(
                    value,
                    (int, float)
                ):

                    feature_vector.append(
                        float(value)
                    )

            recordings.append({

                "filepath": filepath,

                "metrics": metrics,

                "feature_vector": feature_vector
            })

            all_metrics.append(metrics)


        # ---------------------------------
        # BUILD INDIVIDUAL AUDIO TABLE
        # ---------------------------------

        for item in self.individual_tree.get_children():

            self.individual_tree.delete(item)

        metric_names = list(
            all_metrics[0].keys()
        )

        columns = (
            ["Audio"] +
            metric_names +
            ["Vector Length"]
        )

        self.individual_tree["columns"] = columns

        for col in columns:

            self.individual_tree.heading(
                col,
                text=col
            )

            self.individual_tree.column(
                col,
                width=120
            )

        for idx, metrics in enumerate(all_metrics):

            row = [
                f"Audio_{idx+1}"
            ]

            vector_length = len(
                recordings[idx]["feature_vector"]
            )

            for metric in metric_names:

                row.append(
                    metrics[metric]
                )

            row.append(
                vector_length
            )

            self.individual_tree.insert(
                "",
                "end",
                values=row
            )
        save_batch(
            batch_name,
            task,
            recordings
        )

        data = load_research_data()

        aggregate = data[
            batch_name
        ]["aggregate"]

        for item in self.tree.get_children():

            self.tree.delete(item)

        for metric, stats in aggregate.items():

            self.tree.insert(
                "",
                "end",
                values=(

                    metric,

                    stats["mean"],

                    stats["median"],

                    stats["mode"],

                    f"± {stats['std']}"
                )
            )

        messagebox.showinfo(
            "Done",
            "Batch processed successfully."
        )