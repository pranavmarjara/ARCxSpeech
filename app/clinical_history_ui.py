import tkinter as tk
import json
import os

import matplotlib.pyplot as plt
from collections import defaultdict

from tkinter import messagebox

ASSESSMENT_FILE = "clinical_assessments.json"


class ClinicalHistoryWindow:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Clinical History"
        )

        self.root.geometry(
            "1000x700"
        )

        tk.Label(

            root,

            text="Clinical Assessment History",

            font=("Arial",18,"bold")

        ).pack(
            pady=10
        )

        self.listbox = tk.Listbox(

            root,

            width=120,

            height=25

        )

        self.listbox.pack(
            pady=10
        )

        self.load_assessments()

        tk.Button(

            root,

            text="View Assessment",

            command=self.view_assessment,

            width=25,

            height=2

        ).pack(
            pady=10
        )

        tk.Button(

            root,

            text="Show Trends",

            command=self.show_trends,

            width=25,

            height=2

        ).pack(
            pady=10
        )

    def load_assessments(self):

        self.assessments = []

        if not os.path.exists(
            ASSESSMENT_FILE
        ):
            return

        with open(
            ASSESSMENT_FILE,
            "r"
        ) as f:

            self.assessments = json.load(
                f
            )

        self.listbox.delete(
            0,
            tk.END
        )

        for idx, assessment in enumerate(
            self.assessments
        ):

            entry = (

                f"[{idx}] "

                f"ID: {assessment['patient_id']} | "

                f"Age: {assessment['age']} | "

                f"Sex: {assessment['sex']} | "

                f"{assessment['timestamp']}"

            )

            self.listbox.insert(
                tk.END,
                entry
            )

    def view_assessment(self):

        selection = self.listbox.curselection()

        if not selection:
            return

        index = selection[0]

        assessment = self.assessments[
            index
        ]

        window = tk.Toplevel(
            self.root
        )

        window.title(
            "Assessment Details"
        )

        window.geometry(
            "1000x800"
        )

        text = tk.Text(
            window,
            width=120,
            height=50
        )

        text.pack()

        text.insert(
            tk.END,
            json.dumps(
                assessment,
                indent=4
            )
        )


    def show_trends(self):

        if len(patient_records) < 2:

            messagebox.showinfo(
                "Not Enough Data",
                "At least 2 assessments are needed for longitudinal trends."
            )

            return

        selection = self.listbox.curselection()

        if not selection:
            return

        index = selection[0]

        selected = self.assessments[index]

        patient_id = selected["patient_id"]

        patient_records = []

        for assessment in self.assessments:

            if assessment["patient_id"] == patient_id:

                patient_records.append(
                    assessment
                )

        patient_records.sort(
            key=lambda x: x["timestamp"]
        )

        visits = []

        f0_values = []
        f0_range_values = []
        pitch_var_values = []

        hnr_values = []
        jitter_values = []

        ddk_rate_values = []
        ddk_reg_values = []

        speech_rate_values = []
        pause_values = []
        pause_ratio_values = []

        f1_values = []
        f2_values = []

        for i, record in enumerate(
            patient_records
        ):

            visits.append(
                f"V{i+1}"
            )

            vowel = record["vowel_mean"]

            ddk = record["ddk_mean"]

            f0_values.append(
                vowel.get("F0 Mean", 0)
            )

            f0_range_values.append(
                vowel.get("F0 Range", 0)
            )

            pitch_var_values.append(
                vowel.get(
                    "Pitch Variability",
                    0
                )
            )

            hnr_values.append(
                vowel.get("HNR", 0)
            )

            jitter_values.append(
                vowel.get(
                    "Jitter Local",
                    0
                )
            )

            f1_values.append(
                vowel.get(
                    "F1 Mean",
                    0
                )
            )

            f2_values.append(
                vowel.get(
                    "F2 Mean",
                    0
                )
            )

            ddk_rate_values.append(
                ddk.get(
                    "DDK Repetition Rate",
                    0
                )
            )

            ddk_reg_values.append(
                ddk.get(
                    "DDK Regularity",
                    0
                )
            )

            speech_rate_values.append(
                ddk.get(
                    "Speech Rate",
                    0
                )
            )

            pause_values.append(
                ddk.get(
                    "Mean Pause Duration",
                    0
                )
            )

            pause_ratio_values.append(
                ddk.get(
                    "Pause/Speech Ratio",
                    0
                )
            )

        fig, axes = plt.subplots(
            5,
            1,
            figsize=(14,22)
        )

        fig.suptitle(
            f"Patient {patient_id} Longitudinal Trends",
            fontsize=16
        )

        axes[0].plot(
            visits,
            f0_values,
            marker="o",
            label="F0 Mean"
        )

        axes[0].plot(
            visits,
            f0_range_values,
            marker="o",
            label="F0 Range"
        )

        axes[0].plot(
            visits,
            pitch_var_values,
            marker="o",
            label="Pitch Variability"
        )

        axes[0].set_title(
            "Voice Stability",
            pad=15
        )

        axes[0].legend()

        axes[0].grid(True)

        axes[1].plot(
            visits,
            hnr_values,
            marker="o",
            label="HNR"
        )

        axes[1].plot(
            visits,
            jitter_values,
            marker="o",
            label="Jitter Local"
        )

        axes[1].set_title(
            "Voice Quality",
            pad=15
        )

        axes[1].legend()

        axes[1].grid(True)

        axes[2].plot(
            visits,
            ddk_rate_values,
            marker="o",
            label="DDK Rate"
        )

        axes[2].plot(
            visits,
            ddk_reg_values,
            marker="o",
            label="DDK Regularity"
        )

        axes[2].set_title(
            "Articulation",
            pad=15
        )

        axes[2].legend()

        axes[2].grid(True)

        axes[3].plot(
            visits,
            speech_rate_values,
            marker="o",
            label="Speech Rate"
        )

        axes[3].plot(
            visits,
            pause_values,
            marker="o",
            label="Pause Duration"
        )

        axes[3].plot(
            visits,
            pause_ratio_values,
            marker="o",
            label="Pause Ratio"
        )

        axes[3].set_title(
            "Fluency",
            pad=15
        )

        axes[3].legend()

        axes[3].grid(True)

        axes[4].plot(
            visits,
            f1_values,
            marker="o",
            label="F1 Mean"
        )

        axes[4].plot(
            visits,
            f2_values,
            marker="o",
            label="F2 Mean"
        )

        axes[4].set_title(
            "Resonance",
            pad=15
        )

        axes[4].legend()

        axes[4].grid(True)

        plt.tight_layout(
            rect=[0, 0, 1, 0.97]
        )

        fig.subplots_adjust(
            hspace=0.8
        )

        plt.show()