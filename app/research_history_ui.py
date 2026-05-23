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


class ResearchHistoryWindow:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "ARCxSpeech R&D History"
        )

        self.root.geometry("1000x700")

        self.data = load_research_data()

        # -------------------------
        # TITLE
        # -------------------------

        title = tk.Label(
            root,
            text="R&D Batch History",
            font=("Arial", 18, "bold")
        )

        title.pack(pady=10)

        # -------------------------
        # BATCH LIST
        # -------------------------

        tk.Label(
            root,
            text="Research Batches",
            font=("Arial", 12, "bold")
        ).pack(pady=5)

        self.batch_list = tk.Listbox(
            root,
            width=50,
            height=12
        )

        self.batch_list.pack(pady=10)

        for batch_name in self.data.keys():

            self.batch_list.insert(
                tk.END,
                batch_name
            )

        # -------------------------
        # LOAD BUTTON
        # -------------------------

        load_btn = tk.Button(
            root,
            text="Load Batch",
            command=self.load_batch,
            width=20,
            height=2
        )

        load_btn.pack(pady=10)

        # -------------------------
        # SET BASELINE BUTTON
        # -------------------------

        baseline_btn = tk.Button(
            root,
            text="Set Selected Batch as Baseline",
            command=self.set_baseline,
            width=30,
            height=2
        )

        baseline_btn.pack(pady=10)

        # -------------------------
        # DRIFT BUTTON
        # -------------------------

        drift_btn = tk.Button(
            root,
            text="Compute Drift vs Baseline",
            command=self.compute_batch_drift,
            width=30,
            height=2
        )

        drift_btn.pack(pady=10)

        # -------------------------
        # SURVIVABILITY BUTTON
        # -------------------------

        survival_btn = tk.Button(
            root,
            text="Rank Feature Survivability",
            command=self.rank_survivability,
            width=30,
            height=2
        )

        survival_btn.pack(pady=10)

        # -------------------------
        # PCA BUTTON
        # -------------------------

        pca_btn = tk.Button(
            root,
            text="Run PCA Analysis",
            command=self.run_pca_analysis,
            width=30,
            height=2
        )

        pca_btn.pack(pady=10)
        # -------------------------
        # TABLE
        # -------------------------

        columns = (
            "Metric",
            "Mean",
            "Std Dev"
        )

        self.tree = ttk.Treeview(
            root,
            columns=columns,
            show="headings",
            height=20
        )

        for col in columns:

            self.tree.heading(
                col,
                text=col
            )

        self.tree.pack(
            fill="both",
            expand=True,
            padx=20,
            pady=20
        )


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

        # Clear table

        for item in self.tree.get_children():

            self.tree.delete(item)

        # Configure columns

        self.tree["columns"] = (
            "Feature",
            "Drift"
        )

        self.tree.heading(
            "Feature",
            text="Feature"
        )

        self.tree.heading(
            "Drift",
            text="Drift"
        )

        # Insert drift values

        for feature, drift in drift_results.items():

            self.tree.insert(
                "",
                "end",
                values=(
                    feature,
                    drift
                )
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

        # Clear table

        for item in self.tree.get_children():

            self.tree.delete(item)

        # Configure columns

        self.tree["columns"] = (
            "Rank",
            "Feature",
            "Mean Drift"
        )

        self.tree.heading(
            "Rank",
            text="Rank"
        )

        self.tree.heading(
            "Feature",
            text="Feature"
        )

        self.tree.heading(
            "Mean Drift",
            text="Mean Drift"
        )

        self.tree.column(
            "Rank",
            width=80
        )

        self.tree.column(
            "Feature",
            width=250
        )

        self.tree.column(
            "Mean Drift",
            width=150
        )

        # Insert ranking

        for idx, item in enumerate(ranking):

            self.tree.insert(
                "",
                "end",
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

        plt.figure(
            figsize=(10, 8)
        )

        for idx, point in enumerate(transformed):

            x = point[0]

            y = point[1]

            plt.scatter(
                x,
                y
            )

            plt.text(
                x,
                y,
                labels[idx],
                fontsize=8
            )

        plt.xlabel(
            f"PC1 ({variance[0]*100:.2f}% variance)"
        )

        plt.ylabel(
            f"PC2 ({variance[1]*100:.2f}% variance)"
        )

        plt.title(
            "PCA Feature Space Analysis"
        )

        plt.grid(True)

        plt.show()        
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

        batch_name = self.batch_list.get(
            selected[0]
        )

        aggregate = self.data[
            batch_name
        ]["aggregate"]

        # Clear table

        for item in self.tree.get_children():

            self.tree.delete(item)

        # Insert metrics

        for metric, stats in aggregate.items():

            self.tree.insert(
                "",
                "end",
                values=(
                    metric,
                    stats["mean"],
                    f"± {stats['std']}"
                )
            )