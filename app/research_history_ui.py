import tkinter as tk

from tkinter import ttk
from tkinter import messagebox

from app.research_store import (
    load_research_data
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