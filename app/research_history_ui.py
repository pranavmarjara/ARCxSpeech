import tkinter as tk

from tkinter import ttk
from tkinter import messagebox
import matplotlib.pyplot as plt

from app.research_store import (

    load_research_data,

    save_baseline,

    load_baseline,

    compute_drift,

    rank_feature_survivability,

    perform_pca_analysis
)

from app.staged_extraction import STAGE_DEFS, STAGE_KEYS


class ResearchHistoryWindow:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "ARCxSpeech R&D History"
        )

        self.root.geometry("1300x860")

        self.data = load_research_data()

        # Currently loaded batch (set by load_batch) and which
        # preprocessing stage's features are being displayed.
        self.current_batch_name = None
        self.current_batch_data = None
        self.stage_var = tk.StringVar(value=STAGE_KEYS[0])

        # =====================================================
        # ROOT: two columns -- left sidebar | right content
        # =====================================================

        root.columnconfigure(0, weight=0)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=0)
        root.rowconfigure(1, weight=1)

        # -------------------------
        # TITLE (spans both columns)
        # -------------------------

        title = tk.Label(
            root,
            text="R&D Batch History",
            font=("Arial", 18, "bold")
        )

        title.grid(row=0, column=0, columnspan=2, pady=(10, 6))

        # =====================================================
        # LEFT SIDEBAR: batch list + buttons
        # =====================================================

        sidebar = tk.Frame(root, width=240)

        sidebar.grid(
            row=1, column=0,
            sticky="ns",
            padx=(14, 6),
            pady=(0, 14)
        )

        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)

        tk.Label(
            sidebar,
            text="Research Batches",
            font=("Arial", 12, "bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        list_frame = tk.Frame(sidebar)
        list_frame.grid(row=1, column=0, sticky="ew")

        self.batch_list = tk.Listbox(
            list_frame,
            width=28,
            height=12
        )

        list_scroll = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.batch_list.yview
        )

        self.batch_list.configure(
            yscrollcommand=list_scroll.set
        )

        self.batch_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="left", fill="y")

        for batch_name in self.data.keys():

            self.batch_list.insert(
                tk.END,
                batch_name
            )

        # Buttons below the list

        btn_cfg = dict(width=26, height=2)

        for row_idx, (label, cmd) in enumerate([
            ("Load Batch",                 self.load_batch),
            ("Set as Baseline",            self.set_baseline),
            ("Compute Drift vs Baseline",  self.compute_batch_drift),
            ("Rank Feature Survivability", self.rank_survivability),
            ("Run PCA Analysis",           self.run_pca_analysis),
        ], start=2):

            tk.Button(
                sidebar,
                text=label,
                command=cmd,
                **btn_cfg
            ).grid(row=row_idx, column=0, pady=4, sticky="ew")

        # -------------------------
        # PREPROCESSING STAGE SELECTOR
        # -------------------------
        # Empty space below the 5 buttons above: one radio button per
        # cumulative preprocessing stage for the currently loaded batch.
        # Selecting a stage re-renders the aggregate + individual tables
        # using that stage's biomarker features (No Layer / 1 Layer /
        # 2 Layers), so early-layer biomarker shifts can be compared
        # directly against raw audio.

        stage_frame = tk.LabelFrame(
            sidebar,
            text="  Preprocessing Stage  ",
            font=("Arial", 10, "bold"),
            padx=6, pady=6
        )
        stage_frame.grid(row=7, column=0, pady=(10, 4), sticky="ew")

        for stage_key, stage_label, _layers in STAGE_DEFS:
            tk.Radiobutton(
                stage_frame,
                text=stage_label,
                variable=self.stage_var,
                value=stage_key,
                anchor="w",
                justify="left",
                wraplength=190,
                command=self.render_current_stage
            ).pack(fill="x", anchor="w", pady=2)

        # =====================================================
        # RIGHT CONTENT: top = aggregate, bottom = individual
        # =====================================================

        content = tk.Frame(root)

        content.grid(
            row=1, column=1,
            sticky="nsew",
            padx=(6, 14),
            pady=(0, 14)
        )

        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=0)
        content.rowconfigure(1, weight=1)

        # ---- TOP: Aggregate Statistics ----

        agg_frame = tk.LabelFrame(
            content,
            text="  Aggregate Statistics  ",
            font=("Arial", 10, "bold"),
            padx=4, pady=4
        )

        agg_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        agg_frame.columnconfigure(0, weight=1)
        agg_frame.rowconfigure(0, weight=1)

        agg_columns = (
            "Metric",
            "Mean",
            "Median",
            "Mode",
            "Std Dev"
        )

        self.agg_tree = ttk.Treeview(
            agg_frame,
            columns=agg_columns,
            show="headings",
            height=19
        )

        for col in agg_columns:

            self.agg_tree.heading(col, text=col)

            w = 200 if col == "Metric" else 110

            self.agg_tree.column(
                col,
                width=w,
                anchor="w" if col == "Metric" else "center"
            )

        agg_vscroll = ttk.Scrollbar(
            agg_frame,
            orient="vertical",
            command=self.agg_tree.yview
        )

        self.agg_tree.configure(yscrollcommand=agg_vscroll.set)
        self.agg_tree.grid(row=0, column=0, sticky="nsew")
        agg_vscroll.grid(row=0, column=1, sticky="ns")

        # ---- BOTTOM: Individual Recording Values ----

        ind_frame = tk.LabelFrame(
            content,
            text="  Individual Recording Values  ",
            font=("Arial", 10, "bold"),
            padx=4, pady=4
        )

        ind_frame.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        ind_frame.columnconfigure(0, weight=1)
        ind_frame.rowconfigure(0, weight=1)

        self.ind_tree = ttk.Treeview(ind_frame, show="headings", height=6)

        ind_vscroll = ttk.Scrollbar(
            ind_frame,
            orient="vertical",
            command=self.ind_tree.yview
        )

        ind_hscroll = ttk.Scrollbar(
            ind_frame,
            orient="horizontal",
            command=self.ind_tree.xview
        )

        self.ind_tree.configure(
            yscrollcommand=ind_vscroll.set,
            xscrollcommand=ind_hscroll.set
        )

        self.ind_tree.grid(row=0, column=0, sticky="nsew")
        ind_vscroll.grid(row=0, column=1, sticky="ns")
        ind_hscroll.grid(row=1, column=0, sticky="ew")

    # --------------------------------
    # LOAD BATCH
    # --------------------------------

    def load_batch(self):

        selected = self.batch_list.curselection()

        if not selected:

            messagebox.showerror(
                "Error",
                "Select a batch."
            )

            return

        batch_name = self.batch_list.get(selected[0])

        self.current_batch_name = batch_name
        self.current_batch_data = self.data[batch_name]

        self.render_current_stage()

    # --------------------------------
    # LEGACY-FORMAT HELPERS
    # --------------------------------
    # Batches saved before the 3-stage preprocessing comparison was added
    # only have a flat "aggregate" / "metrics" (no per-stage breakdown).
    # These helpers fall back to that flat data for any stage so old
    # batches still display instead of erroring out.

    def _aggregate_for_stage(self, batch_data, stage_key):
        if "aggregate_by_stage" in batch_data:
            return batch_data["aggregate_by_stage"].get(stage_key, {})
        return batch_data.get("aggregate", {})

    def _metrics_for_stage(self, recording, stage_key):
        if "stages" in recording:
            stage = recording["stages"].get(stage_key)
            return stage["metrics"] if stage else {}
        return recording.get("metrics", {})

    # --------------------------------
    # RENDER CURRENT STAGE
    # --------------------------------
    # Re-renders the aggregate + individual tables for whichever batch is
    # currently loaded, using whichever preprocessing stage is selected
    # via the radio buttons.

    def render_current_stage(self):

        if self.current_batch_data is None:
            return

        batch_data = self.current_batch_data
        stage_key = self.stage_var.get()

        aggregate  = self._aggregate_for_stage(batch_data, stage_key)
        recordings = batch_data.get("recordings", [])

        # ---- Aggregate table (top) ----

        for item in self.agg_tree.get_children():
            self.agg_tree.delete(item)

        self.agg_tree["columns"] = (
            "Metric", "Mean", "Median", "Mode", "Std Dev"
        )

        self.agg_tree.heading("Metric", text="Metric")
        self.agg_tree.heading("Mean", text="Mean")
        self.agg_tree.heading("Median", text="Median")
        self.agg_tree.heading("Mode", text="Mode")
        self.agg_tree.heading("Std Dev", text="Std Dev")

        self.agg_tree.column("Metric", width=200, anchor="w")
        self.agg_tree.column("Mean", width=110, anchor="center")
        self.agg_tree.column("Median", width=110, anchor="center")
        self.agg_tree.column("Mode", width=110, anchor="center")
        self.agg_tree.column("Std Dev", width=110, anchor="center")

        for metric, stats in aggregate.items():

            self.agg_tree.insert(
                "", "end",
                values=(
                    metric,
                    stats["mean"],
                    stats["median"],
                    stats["mode"],
                    f"± {stats['std']}"
                )
            )

        # ---- Individual recordings table (bottom) ----

        for item in self.ind_tree.get_children():
            self.ind_tree.delete(item)

        if not recordings:

            self.ind_tree["columns"] = ("Info",)
            self.ind_tree.heading("Info", text="No individual recordings stored.")
            self.ind_tree.column("Info", width=400, anchor="w")
            return

        first_metrics = self._metrics_for_stage(recordings[0], stage_key)
        metric_keys = list(first_metrics.keys())

        col_ids = ["Recording"] + metric_keys

        self.ind_tree["columns"] = col_ids

        self.ind_tree.heading("Recording", text="Recording")
        self.ind_tree.column("Recording", width=100, anchor="center", stretch=False)

        for key in metric_keys:
            self.ind_tree.heading(key, text=key)
            self.ind_tree.column(key, width=110, anchor="center", stretch=False)

        for idx, rec in enumerate(recordings):

            label = f"Audio_{idx + 1}"

            metrics = self._metrics_for_stage(rec, stage_key)

            row = [label]

            for key in metric_keys:

                val = metrics.get(key, "")

                if isinstance(val, float):
                    val = round(val, 4)

                row.append(val)

            self.ind_tree.insert("", "end", values=row)

    # --------------------------------
    # SET BASELINE
    # --------------------------------

    def set_baseline(self):

        selected = self.batch_list.curselection()

        if not selected:

            messagebox.showerror(
                "Error",
                "Select a batch."
            )

            return

        batch_name = self.batch_list.get(
            selected[0]
        )

        aggregate = self.data[
            batch_name
        ]["aggregate"]

        save_baseline(
            batch_name,
            aggregate
        )

        messagebox.showinfo(
            "Baseline Set",
            f"{batch_name} is now baseline."
        )

    # --------------------------------
    # COMPUTE DRIFT
    # --------------------------------

    def compute_batch_drift(self):

        baseline = load_baseline()

        if baseline is None:

            messagebox.showerror(
                "Error",
                "No baseline selected."
            )

            return

        selected = self.batch_list.curselection()

        if not selected:

            messagebox.showerror(
                "Error",
                "Select a noise batch."
            )

            return

        batch_name = self.batch_list.get(
            selected[0]
        )

        noise_aggregate = self.data[
            batch_name
        ]["aggregate"]

        baseline_aggregate = baseline[
            "aggregate"
        ]

        drift_results = compute_drift(
            baseline_aggregate,
            noise_aggregate
        )

        for item in self.agg_tree.get_children():
            self.agg_tree.delete(item)

        self.agg_tree["columns"] = ("Feature", "Drift")

        self.agg_tree.heading("Feature", text="Feature")
        self.agg_tree.heading("Drift", text="Drift")

        self.agg_tree.column("Feature", width=220, anchor="w")
        self.agg_tree.column("Drift", width=120, anchor="center")

        for feature, drift in drift_results.items():

            self.agg_tree.insert(
                "", "end",
                values=(feature, drift)
            )

        messagebox.showinfo(
            "Done",
            "Drift analysis complete."
        )

    # --------------------------------
    # FEATURE SURVIVABILITY
    # --------------------------------

    def rank_survivability(self):

        baseline = load_baseline()

        if baseline is None:

            messagebox.showerror(
                "Error",
                "No baseline selected."
            )

            return

        baseline_aggregate = baseline[
            "aggregate"
        ]

        ranking = rank_feature_survivability(
            baseline_aggregate,
            self.data
        )

        for item in self.agg_tree.get_children():
            self.agg_tree.delete(item)

        self.agg_tree["columns"] = ("Rank", "Feature", "Mean Drift")

        self.agg_tree.heading("Rank", text="Rank")
        self.agg_tree.heading("Feature", text="Feature")
        self.agg_tree.heading("Mean Drift", text="Mean Drift")

        self.agg_tree.column("Rank", width=60, anchor="center")
        self.agg_tree.column("Feature", width=220, anchor="w")
        self.agg_tree.column("Mean Drift", width=120, anchor="center")

        for idx, item in enumerate(ranking):

            self.agg_tree.insert(
                "", "end",
                values=(
                    idx + 1,
                    item["feature"],
                    item["mean_drift"]
                )
            )

        messagebox.showinfo(
            "Done",
            "Feature survivability ranking complete."
        )

    # --------------------------------
    # PCA ANALYSIS
    # --------------------------------

    def run_pca_analysis(self):

        transformed, labels, variance = perform_pca_analysis(
            self.data
        )

        if transformed is None:

            messagebox.showerror(
                "Error",
                "Not enough data for PCA."
            )

            return

        plt.figure(figsize=(10, 8))

        for idx, point in enumerate(transformed):

            x, y = point[0], point[1]

            plt.scatter(x, y)

            plt.text(x, y, labels[idx], fontsize=8)

        plt.xlabel(f"PC1 ({variance[0]*100:.2f}% variance)")
        plt.ylabel(f"PC2 ({variance[1]*100:.2f}% variance)")
        plt.title("PCA Feature Space Analysis")
        plt.grid(True)
        plt.show()
