import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

from app.recorder import record_audio

from app.config import (
    VOWEL_DURATION,
    DDK_DURATION
)

from app.feature_extractor import (
    extract_vowel_features,
    extract_ddk_features
)

from app.assessment_store import (
    save_assessment
)

import numpy as np

class AssessmentWindow:

    

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Clinical Assessment"
        )

        self.root.geometry(
            "700x600"
        )

        
        self.vowel_files = []

        self.ddk_files = []

        self.vowel_count = 0

        self.ddk_count = 0

        tk.Label(
            root,
            text="Patient Assessment",
            font=("Arial",18,"bold")
        ).pack(pady=20)

        tk.Label(
            root,
            text="Patient Name"
        ).pack()

        self.name_entry = tk.Entry(
            root,
            width=40
        )

        self.name_entry.pack(pady=5)

        tk.Label(
            root,
            text="Patient ID"
        ).pack()

        self.id_entry = tk.Entry(
            root,
            width=40
        )

        self.id_entry.pack(pady=5)

        tk.Label(
            root,
            text="Age"
        ).pack()

        self.age_entry = tk.Entry(
            root,
            width=40
        )

        self.age_entry.pack(pady=5)

        tk.Label(
            root,
            text="Sex"
        ).pack()

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

        self.sex_dropdown.pack(
            pady=5
        )

        tk.Button(

            root,

            text="Start Assessment",

            command=self.start_assessment,

            width=25,

            height=2

        ).pack(
            pady=30
        )

    def start_assessment(self):

        patient_name = self.name_entry.get()

        patient_id = self.id_entry.get()

        age = self.age_entry.get()

        sex = self.sex_var.get()

        if not patient_name:

            messagebox.showerror(
                "Error",
                "Enter patient name."
            )

            return

        if not patient_id:

            messagebox.showerror(
                "Error",
                "Enter patient ID."
            )

            return

        if not age:

            messagebox.showerror(
                "Error",
                "Enter age."
            )

            return

        if not sex:

            messagebox.showerror(
                "Error",
                "Select sex."
            )

            return

        self.patient_name = patient_name
        self.patient_id = patient_id
        self.age = age
        self.sex = sex

        self.build_recording_screen()


    def build_recording_screen(self):

        for widget in self.root.winfo_children():
            widget.destroy()

        tk.Label(
            self.root,
            text="Clinical Assessment",
            font=("Arial",18,"bold")
        ).pack(pady=20)

        tk.Label(
            self.root,
            text=(
                "Record Sustained Vowel (/a/) 3 Times\n"
                f"Duration: {VOWEL_DURATION} sec"
            )
        ).pack(pady=10)

        self.vowel_status = tk.Label(
            self.root,
            text="Completed: 0 / 3"
        )

        self.vowel_status.pack()

        tk.Button(
            self.root,
            text="Record Vowel Trial",
            command=self.record_vowel,
            width=25,
            height=2
        ).pack(pady=10)

        tk.Label(
            self.root,
            text=(
                "Record DDK (pataka) 3 Times\n"
                f"Duration: {DDK_DURATION} sec"
            )
        ).pack(pady=20)

        self.ddk_status = tk.Label(
            self.root,
            text="Completed: 0 / 3"
        )

        self.ddk_status.pack()

        tk.Button(
            self.root,
            text="Record DDK Trial",
            command=self.record_ddk,
            width=25,
            height=2
        ).pack(pady=10)

        self.process_btn = tk.Button(
            self.root,
            text="Process Assessment",
            state="disabled",
            command=self.process_assessment,
            width=30,
            height=2
        )

        self.process_btn.pack(pady=40)

    def record_vowel(self):

        if self.vowel_count >= 3:
            return

        filepath, _ = record_audio(
            VOWEL_DURATION,
            prefix="vowel"
        )

        self.vowel_files.append(
            filepath
        )

        self.vowel_count += 1

        self.vowel_status.config(
            text=f"Completed: {self.vowel_count} / 3"
        )

        self.check_ready()

    def record_ddk(self):

        if self.ddk_count >= 3:
            return

        filepath, _ = record_audio(
            DDK_DURATION,
            prefix="ddk"
        )

        self.ddk_files.append(
            filepath
        )

        self.ddk_count += 1

        self.ddk_status.config(
            text=f"Completed: {self.ddk_count} / 3"
        )

        self.check_ready()

    def check_ready(self):

        if (
            self.vowel_count == 3
            and
            self.ddk_count == 3
        ):

            self.process_btn.config(
                state="normal"
            )


    def process_assessment(self):

        vowel_results = []

        for file in self.vowel_files:

            vowel_results.append(
                extract_vowel_features(
                    file
                )
            )

        ddk_results = []

        for file in self.ddk_files:

            ddk_results.append(
                extract_ddk_features(
                    file
                )
            )

        vowel_mean = self.average_metrics(
            vowel_results
        )

        ddk_mean = self.average_metrics(
            ddk_results
        )

        vowel_sd = self.metric_sd(
            vowel_results
        )

        ddk_sd = self.metric_sd(
            ddk_results
        )

        save_assessment(

            self.patient_name,

            self.patient_id,

            self.age,

            self.sex,

            vowel_results,

            ddk_results,

            vowel_mean,

            ddk_mean,

            self.vowel_files,

            self.ddk_files
        )

        from datetime import datetime

        assessment_time = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        self.show_results(

            self.patient_id,

            self.age,

            self.sex,

            assessment_time,

            vowel_mean,
            vowel_sd,

            ddk_mean,
            ddk_sd
        )

    def show_results(

        self,

        patient_id,

        age,

        sex,

        assessment_time,

        vowel_mean,
        vowel_sd,

        ddk_mean,
        ddk_sd
    ):

        result_window = tk.Toplevel(
            self.root
        )

        result_window.title(
            "Assessment Results"
        )

        result_window.geometry(
            "900x700"
        )

        tk.Label(

            result_window,

            text="ASSESSMENT INFORMATION",

            font=("Arial",14,"bold")

        ).pack(
            pady=10
        )

        metadata_text = (
            f"Patient ID: {patient_id}\n"
            f"Age: {age}\n"
            f"Sex: {sex}\n"
            f"Assessment Date: {assessment_time}"
        )

        tk.Label(

            result_window,

            text=metadata_text,

            font=("Arial",11),

            justify="left"

        ).pack(
            pady=10
        )

        tk.Label(

            result_window,

            text="SUSTAINED VOWEL",

            font=("Arial",14,"bold")

        ).pack(
            pady=10
        )

        vowel_text = tk.Text(
            result_window,
            height=18,
            width=70
        )

        vowel_text.pack()

        for key, value in vowel_mean.items():

            sd = vowel_sd.get(
                key,
                0
            )

            vowel_text.insert(
                tk.END,
                f"{key}: {value} ± {sd}\n"
            )

        tk.Label(

            result_window,

            text="DDK",

            font=("Arial",14,"bold")

        ).pack(
            pady=10
        )

        ddk_text = tk.Text(
            result_window,
            height=18,
            width=70
        )

        ddk_text.pack()

        for key, value in ddk_mean.items():

            sd = ddk_sd.get(
                key,
                0
            )

            ddk_text.insert(
                tk.END,
                f"{key}: {value} ± {sd}\n"
            ) 

    def average_metrics(
        self,
        metrics_list
    ):

        averaged = {}

        keys = metrics_list[0].keys()

        for key in keys:

            values = []

            for m in metrics_list:

                value = m[key]

                if isinstance(
                    value,
                    (int, float)
                ):

                    values.append(
                        value
                    )

            if len(values) > 0:

                averaged[key] = round(
                    float(
                        np.mean(
                            values
                        )
                    ),
                    3
                )

        return averaged
    

    def metric_sd(
        self,
        metrics_list
    ):

        sd_dict = {}

        keys = metrics_list[0].keys()

        for key in keys:

            values = []

            for m in metrics_list:

                value = m[key]

                if isinstance(
                    value,
                    (int, float)
                ):

                    values.append(value)

            if len(values) > 1:

                sd_dict[key] = round(
                    float(np.std(values)),
                    3
                )

        return sd_dict