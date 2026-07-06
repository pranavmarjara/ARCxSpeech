import tkinter as tk
from tkinter import ttk
from tkinter import messagebox

import threading
import time

from app.recorder import record_audio

from app.config import (
    VOWEL_DURATION,
    DDK_DURATION
)

from app.feature_extractor import (
    extract_vowel_features,
    extract_ddk_features
)

from app.ambient_analyzer import (
    extract_ambient_metrics
)

from app.assessment_store import (
    save_assessment
)

from app.window_nav import open_child_window

import numpy as np


class AssessmentResultsWindow:

    def __init__(
        self,
        root,
        patient_id,
        age,
        sex,
        assessment_time,
        vowel_mean,
        vowel_sd,
        ddk_mean,
        ddk_sd,
        ambient_mean,
        ambient_sd
    ):

        self.root = root

        self.root.title(
            "Assessment Results"
        )

        self.root.geometry(
            "1100x700"
        )
        
        
        tk.Label(
            root,
            text="ASSESSMENT INFORMATION",
            font=("Arial", 14, "bold")
        ).pack(pady=(45, 10))

        metadata_text = (
            f"Patient ID: {patient_id}\n"
            f"Age: {age}\n"
            f"Sex: {sex}\n"
            f"Assessment Date: {assessment_time}"
        )

        tk.Label(
            root,
            text=metadata_text,
            font=("Arial", 11),
            justify="left"
        ).pack(pady=10)

        tk.Label(
            root,
            text="SUSTAINED VOWEL",
            font=("Arial", 14, "bold")
        ).pack(pady=10)

        vowel_text = tk.Text(
            root,
            height=18,
            width=70
        )

        vowel_text.pack()

        for key, value in vowel_mean.items():

            sd = vowel_sd.get(key, 0)

            vowel_text.insert(
                tk.END,
                f"{key}: {value} ± {sd}\n"
            )


        tk.Label(
            root,
            text="AMBIENT ANALYSIS",
            font=("Arial", 14, "bold")
        ).pack(pady=10)

        ambient_text = tk.Text(
            root,
            height=10,
            width=70
        )

        ambient_text.pack()

        for key, value in ambient_mean.items():

            sd = ambient_sd.get(key, 0)

            ambient_text.insert(
                tk.END,
                f"{key}: {value} ± {sd}\n"
            )


        tk.Label(
            root,
            text="DDK",
            font=("Arial", 14, "bold")
        ).pack(pady=10)

        ddk_text = tk.Text(
            root,
            height=18,
            width=70
        )

        ddk_text.pack()

        for key, value in ddk_mean.items():

            sd = ddk_sd.get(key, 0)

            ddk_text.insert(
                tk.END,
                f"{key}: {value} ± {sd}\n"
            )


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

        try:
            age = int(age)

        except ValueError:

            messagebox.showerror(
                "Invalid Age",
                "Age must be a whole number (e.g. 34)."
            )

            return

        if age <= 0 or age > 130:

            messagebox.showerror(
                "Invalid Age",
                "Age must be a realistic value between 1 and 130."
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

        self.record_vowel_btn = tk.Button(
            self.root,
            text="Record Vowel Trial",
            command=self.record_vowel,
            width=25,
            height=2
        )

        self.record_vowel_btn.pack(pady=10)

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

        self.record_ddk_btn = tk.Button(
            self.root,
            text="Record DDK Trial",
            command=self.record_ddk,
            width=25,
            height=2
        )

        self.record_ddk_btn.pack(pady=10)

        self.status_label = tk.Label(
            self.root,
            text="",
            font=("Arial", 11, "bold")
        )

        self.status_label.pack(pady=(15, 5))

        self.progress_bar = ttk.Progressbar(
            self.root,
            orient="horizontal",
            length=300,
            mode="determinate",
            maximum=100
        )

        self.progress_bar.pack(pady=(0, 10))

        self.process_btn = tk.Button(
            self.root,
            text="Process Assessment",
            state="disabled",
            command=self.process_assessment,
            width=30,
            height=2
        )

        self.process_btn.pack(pady=40)

    def _start_recording_flow(self, duration, prefix, on_success):

        self.record_vowel_btn.config(state="disabled")
        self.record_ddk_btn.config(state="disabled")
        self.process_btn.config(state="disabled")

        self.progress_bar["value"] = 0

        self._countdown(3, duration, prefix, on_success)

    def _countdown(self, seconds_left, duration, prefix, on_success):

        if seconds_left > 0:

            self.status_label.config(
                text=f"Recording starts in: {seconds_left}"
            )

            self.root.after(
                1000,
                lambda: self._countdown(
                    seconds_left - 1,
                    duration,
                    prefix,
                    on_success
                )
            )

            return

        self.status_label.config(
            text=f"Recording... ({duration} sec)"
        )

        result = {}

        def worker():

            try:

                filepath, audio = record_audio(
                    duration,
                    prefix=prefix
                )

                result["filepath"] = filepath
                result["audio"] = audio

            except Exception as e:

                # Caught here rather than left to crash the background
                # thread silently -- store it so _poll_recording (running
                # on the main/UI thread) can show it to the user instead
                # of proceeding as if recording succeeded.
                result["error"] = e

        thread = threading.Thread(
            target=worker,
            daemon=True
        )

        thread.start()

        start_time = time.time()

        self._poll_recording(
            thread,
            start_time,
            duration,
            result,
            on_success
        )

    def _poll_recording(
        self,
        thread,
        start_time,
        duration,
        result,
        on_success
    ):

        elapsed = time.time() - start_time

        progress = min(100, (elapsed / duration) * 100)

        self.progress_bar["value"] = progress

        if thread.is_alive():

            self.root.after(
                100,
                lambda: self._poll_recording(
                    thread,
                    start_time,
                    duration,
                    result,
                    on_success
                )
            )

            return

        self.record_vowel_btn.config(state="normal")
        self.record_ddk_btn.config(state="normal")

        error = result.get("error")

        if error is not None:

            self.progress_bar["value"] = 0

            self.status_label.config(
                text="Recording failed."
            )

            messagebox.showerror(
                "Recording Failed",
                f"The recording could not be completed:\n\n{error}\n\n"
                "Please check the device connection and try again."
            )

            return

        self.progress_bar["value"] = 100

        self.status_label.config(
            text="Recording complete."
        )

        on_success(
            result["filepath"],
            result["audio"]
        )

        self.check_ready()

    def record_vowel(self):

        if self.vowel_count >= 3:
            return

        def on_success(filepath, audio):

            self.vowel_files.append(
                filepath
            )

            self.vowel_count += 1

            self.vowel_status.config(
                text=f"Completed: {self.vowel_count} / 3"
            )

        self._start_recording_flow(
            VOWEL_DURATION,
            "vowel",
            on_success
        )

    def record_ddk(self):

        if self.ddk_count >= 3:
            return

        def on_success(filepath, audio):

            self.ddk_files.append(
                filepath
            )

            self.ddk_count += 1

            self.ddk_status.config(
                text=f"Completed: {self.ddk_count} / 3"
            )

        self._start_recording_flow(
            DDK_DURATION,
            "ddk",
            on_success
        )

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

        ambient_results = []

        all_files = self.vowel_files + self.ddk_files

        for file in all_files:

            ambient_results.append(
                extract_ambient_metrics(
                    file
                )
            )

        ambient_mean = self.average_metrics(
            ambient_results
        )

        ambient_sd = self.metric_sd(
            ambient_results
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

            ambient_mean,

            self.vowel_files,

            self.ddk_files,

            vowel_sd,

            ddk_sd,

            ambient_sd
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
            ddk_sd,
            ambient_mean,
            ambient_sd
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
        ddk_sd,
        ambient_mean,
        ambient_sd
    ):

        open_child_window(
            self.root,
            AssessmentResultsWindow,
            patient_id,
            age,
            sex,
            assessment_time,
            vowel_mean,
            vowel_sd,
            ddk_mean,
            ddk_sd,
            ambient_mean,
            ambient_sd
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