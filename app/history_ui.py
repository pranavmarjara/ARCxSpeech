import json

import tkinter as tk

from tkinter import ttk
from tkinter import messagebox

import matplotlib.pyplot as plt

from app.session_store import load_sessions


class HistoryWindow:

    def __init__(self, root):

        self.root = root

        self.root.title("ARCxSpeech History")

        self.root.geometry("800x600")

        self.data = load_sessions()

        # ----------------------------
        # PATIENT SELECTOR
        # ----------------------------

        tk.Label(
            root,
            text="Select Patient",
            font=("Arial", 14, "bold")
        ).pack(pady=10)

        self.patient_var = tk.StringVar()

        self.patient_dropdown = ttk.Combobox(
            root,
            textvariable=self.patient_var,
            values=list(self.data.keys()),
            state="readonly",
            width=40
        )

        self.patient_dropdown.pack(pady=10)

        self.patient_dropdown.bind(
            "<<ComboboxSelected>>",
            self.load_patient_sessions
        )

        # ----------------------------
        # SESSION LIST
        # ----------------------------

        self.session_list = tk.Listbox(
            root,
            width=80,
            height=15
        )

        self.session_list.pack(pady=10)

        # ----------------------------
        # METRIC DROPDOWN
        # ----------------------------

        tk.Label(
            root,
            text="Select Metric",
            font=("Arial", 12, "bold")
        ).pack(pady=10)

        self.metric_var = tk.StringVar()

        self.metric_dropdown = ttk.Combobox(
            root,
            textvariable=self.metric_var,
            width=40,
            state="readonly"
        )

        self.metric_dropdown.pack(pady=10)

        # ----------------------------
        # GRAPH BUTTON
        # ----------------------------

        graph_btn = tk.Button(
            root,
            text="Show Line Graph",
            command=self.show_graph,
            width=25,
            height=2
        )

        graph_btn.pack(pady=20)

        # ----------------------------
        # CLEAR HISTORY BUTTON
        # ----------------------------

        clear_btn = tk.Button(
            root,
            text="Clear Entire History",
            command=self.clear_history,
            width=25,
            height=2,
            bg="red",
            fg="white"
        )

        clear_btn.pack(pady=10)

    # --------------------------------
    # LOAD PATIENT SESSIONS
    # --------------------------------

    def load_patient_sessions(self, event=None):

        patient = self.patient_var.get()

        self.session_list.delete(0, tk.END)

        sessions = self.data.get(patient, [])

        if not sessions:
            return

        for session in sessions:

            entry = (
                f"{session['timestamp']} | "
                f"{session['task']}"
            )

            self.session_list.insert(
                tk.END,
                entry
            )

        metrics = list(
            sessions[0]["metrics"].keys()
        )

        self.metric_dropdown["values"] = metrics

    # --------------------------------
    # SHOW GRAPH
    # --------------------------------

    def show_graph(self):

        patient = self.patient_var.get()

        metric = self.metric_var.get()

        if not patient or not metric:

            messagebox.showerror(
                "Error",
                "Select patient and metric."
            )

            return

        sessions = self.data.get(patient, [])

        x = []
        y = []

        for idx, session in enumerate(sessions):

            metrics = session["metrics"]

            if metric in metrics:

                x.append(idx + 1)

                y.append(metrics[metric])

        if not y:

            messagebox.showerror(
                "Error",
                "No metric data found."
            )

            return

        plt.figure(figsize=(8, 5))

        plt.plot(
            x,
            y,
            marker="o"
        )

        plt.xlabel("Session")

        plt.ylabel(metric)

        plt.title(f"{metric} Trend")

        plt.grid(True)

        plt.show()

    # --------------------------------
    # CLEAR HISTORY
    # --------------------------------

    def clear_history(self):

        confirm = messagebox.askyesno(
            "Confirm Delete",
            "Are you sure you want to delete the entire history database?"
        )

        if not confirm:
            return

        with open("sessions.json", "w") as f:
            json.dump({}, f, indent=4)

        self.data = {}

        self.patient_dropdown["values"] = []

        self.session_list.delete(0, tk.END)

        self.metric_dropdown["values"] = []

        messagebox.showinfo(
            "History Cleared",
            "Entire session history deleted."
        )    