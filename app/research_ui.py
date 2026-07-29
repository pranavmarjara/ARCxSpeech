import tkinter as tk

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

from app.staged_extraction import (
    run_staged_extraction,
    STAGE_KEYS
)

from app.research_store import (
    save_batch,
    load_research_data
)

from app.research_history_ui import (
    ResearchHistoryWindow
)

from app.window_nav import open_child_window

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
        # SPEAKER ID
        # -------------------------

        tk.Label(
            root,
            text="Speaker ID"
        ).pack()

        self.speaker_entry = tk.Entry(
            root,
            width=40
        )

        self.speaker_entry.pack(pady=5)

        # -------------------------
        # DEVICE
        # -------------------------

        tk.Label(
            root,
            text="Device"
        ).pack()

        self.device_entry = tk.Entry(
            root,
            width=40
        )

        self.device_entry.pack(pady=5)

        # -------------------------
        # ENVIRONMENT
        # -------------------------

        tk.Label(
            root,
            text="Environment"
        ).pack()

        self.environment_entry = tk.Entry(
            root,
            width=40
        )

        self.environment_entry.pack(pady=5)

        # -------------------------
        # MIC DISTANCE
        # -------------------------

        tk.Label(
            root,
            text="Mic Distance (cm)"
        ).pack()

        self.distance_entry = tk.Entry(
            root,
            width=40
        )

        self.distance_entry.pack(pady=5)

        # -------------------------
        # NOTES
        # -------------------------

        tk.Label(
            root,
            text="Notes"
        ).pack()

        self.notes_entry = tk.Entry(
            root,
            width=60
        )

        self.notes_entry.pack(pady=5)
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

        open_child_window(self.root, ResearchHistoryWindow)

    # ---------------------------------
    # PROCESS BATCH
    # ---------------------------------

    def process_batch(self):

        batch_name = self.batch_entry.get()
        speaker_id = self.speaker_entry.get()

        device = self.device_entry.get()

        environment = self.environment_entry.get()

        distance = self.distance_entry.get()

        notes = self.notes_entry.get()

        task = self.task_var.get()

        if not batch_name or not task:

            messagebox.showerror(
                "Error",
                "Enter batch name and task."
            )

            return

        if distance:

            try:
                distance = float(distance)

            except ValueError:

                messagebox.showerror(
                    "Invalid Distance",
                    "Mic Distance (cm) must be a number, e.g. 15 or 15.5."
                )

                return

        existing_data = load_research_data()

        if batch_name in existing_data:

            overwrite = messagebox.askyesno(
                "Batch Name Already Exists",
                f"A batch named '{batch_name}' already exists and has "
                f"{len(existing_data[batch_name].get('recordings', []))} "
                "recording(s) saved.\n\n"
                "Continuing will permanently overwrite that batch's data. "
                "Do you want to overwrite it?"
            )

            if not overwrite:
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

        # Full-pipeline stage (both layers applied) -- this is what the
        # "Process Batch" screen shows immediately below. All 3 stages
        # are still computed and saved so R&D History can compare them.
        full_stage_key = STAGE_KEYS[-1]

        for filepath in self.filepaths:

            stage_results = run_staged_extraction(
                filepath,
                task
            )

            full_metrics = stage_results[full_stage_key]["metrics"]

            feature_vector = []

            for value in full_metrics.values():

                if isinstance(
                    value,
                    (int, float)
                ):

                    feature_vector.append(
                        float(value)
                    )

            recordings.append({

                "filepath": filepath,

                "stages": stage_results,

                "feature_vector": feature_vector
            })

            all_metrics.append(full_metrics)


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
            recordings,
            speaker_id,
            device,
            environment,
            distance,
            notes
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