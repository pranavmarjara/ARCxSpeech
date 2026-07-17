# REPLACEMENT:
import tkinter as tk

from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg,
    NavigationToolbar2Tk
)

from tkinter import messagebox

from app.window_nav import open_child_window
from app.config import DDK_DURATION

# Single source of truth for where assessments live -- this used to be
# redefined here as a bare relative filename, which resolved against
# whatever the process's working directory happened to be at launch
# instead of the app's actual install location. If ARCxSpeech was ever
# started from a different working directory (a desktop shortcut, a
# different IDE run config, a packaged .exe, a scheduled task), this
# screen would silently show an empty history while assessment_store.py
# had been correctly saving every assessment to the real file the whole
# time. Importing both the path and the loader from assessment_store.py
# means this file can no longer drift from where the writer actually
# writes.
from app.assessment_store import (
    ASSESSMENT_FILE,
    load_assessments as load_assessments_from_store
)


class AssessmentDetailWindow:

    def __init__(self, root, assessment):

        self.root = root

        self.root.title(
            "Assessment Details"
        )

        self.root.geometry(
            "1000x800"
        )

        text = tk.Text(
            root,
            width=140,
            height=45,
            font=("Consolas", 10)
        )

        text.pack(
            fill="both",
            expand=True,
            padx=15,
            pady=15
        )

        text.insert(
            tk.END,
            "==============================\n"
        )

        text.insert(
            tk.END,
            "PATIENT INFORMATION\n"
        )

        text.insert(
            tk.END,
            "==============================\n\n"
        )

        text.insert(
            tk.END,
            f"Patient Name : {assessment['patient_name']}\n"
        )

        text.insert(
            tk.END,
            f"Patient ID   : {assessment['patient_id']}\n"
        )

        text.insert(
            tk.END,
            f"Age          : {assessment['age']}\n"
        )

        text.insert(
            tk.END,
            f"Sex          : {assessment['sex']}\n"
        )

        text.insert(
            tk.END,
            f"Assessment   : {assessment['timestamp']}\n\n"
        )

        text.insert(
            tk.END,
            "==============================\n"
        )

        text.insert(
            tk.END,
            "SUSTAINED VOWEL\n"
        )

        text.insert(
            tk.END,
            "==============================\n\n"
        )

        for key, value in assessment["vowel_mean"].items():

            sd = assessment.get(
                "vowel_sd",
                {}
            ).get(
                key,
                0
            )

            text.insert(
                tk.END,
                f"{key:<30}{value} ± {sd}\n"
            )

        text.insert(
            tk.END,
            "\n==============================\n"
        )

        text.insert(
            tk.END,
            "DDK ANALYSIS\n"
        )

        text.insert(
            tk.END,
            "==============================\n\n"
        )

        for key, value in assessment["ddk_mean"].items():

            sd = assessment.get(
                "ddk_sd",
                {}
            ).get(
                key,
                0
            )

            text.insert(
                tk.END,
                f"{key:<30}{value} ± {sd}\n"
            )

        text.insert(
            tk.END,
            "\n==============================\n"
        )

        text.insert(
            tk.END,
            "AMBIENT ANALYSIS\n"
        )

        text.insert(
            tk.END,
            "==============================\n\n"
        )

        for key, value in assessment.get(
            "ambient_mean",
            {}
        ).items():

            sd = assessment.get(
                "ambient_sd",
                {}
            ).get(
                key,
                0
            )

            text.insert(
                tk.END,
                f"{key:<30}{value} ± {sd}\n"
            )

        recording_quality_classification = assessment.get(
            "recording_quality_classification",
            {}
        )

        recording_quality_mean = assessment.get(
            "recording_quality_mean",
            {}
        )

        recording_quality_sd = assessment.get(
            "recording_quality_sd",
            {}
        )

        # Older assessments saved before the Recording Quality Engine
        # was integrated won't have this data -- skip the section
        # entirely rather than showing an empty/misleading block.
        if recording_quality_classification or recording_quality_mean:

            text.insert(
                tk.END,
                "\n==============================\n"
            )

            text.insert(
                tk.END,
                "RECORDING QUALITY\n"
            )

            text.insert(
                tk.END,
                "==============================\n\n"
            )

            text.insert(
                tk.END,
                f"Rating       : {recording_quality_classification.get('Recording Quality Rating', 'N/A')}\n"
            )

            text.insert(
                tk.END,
                f"Score        : {recording_quality_classification.get('Recording Quality Score', 'N/A')}\n"
            )

            text.insert(
                tk.END,
                f"Environment  : {recording_quality_classification.get('Environment', 'N/A')}\n"
            )

            text.insert(
                tk.END,
                f"Confidence   : {recording_quality_classification.get('Confidence', 'N/A')}\n"
            )

            text.insert(
                tk.END,
                f"Recommendation: {recording_quality_classification.get('Recommendation', 'N/A')}\n\n"
            )

            for key, value in recording_quality_mean.items():

                sd = recording_quality_sd.get(
                    key,
                    0
                )

                text.insert(
                    tk.END,
                    f"{key:<30}{value} ± {sd}\n"
                )

        text.config(
            state="disabled"
        )

class _TrendPlotWindow:
    """
    Embeds a matplotlib Figure in its own Toplevel via
    FigureCanvasTkAgg, managed the same way as every other window in
    this app (open_child_window), instead of calling plt.show() and
    handing control to a second, separate GUI event loop.
    """

    def __init__(self, root, fig, title="Trends"):

        self.root = root
        self.fig = fig

        self.root.title(title)
        self.root.geometry("1100x900")

        canvas = FigureCanvasTkAgg(fig, master=root)
        canvas.draw()

        toolbar = NavigationToolbar2Tk(canvas, root)
        toolbar.update()

        canvas.get_tk_widget().pack(fill="both", expand=True)
        
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

    # REPLACEMENT:
    def load_assessments(self):

        try:

            self.assessments = load_assessments_from_store()

        except RuntimeError as e:

            # load_assessments_from_store() raises this on a corrupted
            # JSON file rather than crashing -- surface it instead of
            # letting the app die on an unhandled JSONDecodeError.
            self.assessments = []

            messagebox.showerror(
                "Data File Error",
                str(e)
            )

        self.listbox.delete(
            0,
            tk.END
        )

        for idx, assessment in enumerate(
            self.assessments
        ):

            rq_rating = assessment.get(
                "recording_quality_classification",
                {}
            ).get(
                "Recording Quality Rating"
            )

            rq_suffix = (
                f" | Quality: {rq_rating}"
                if rq_rating
                else ""
            )

            entry = (

                f"[{idx}] "

                f"ID: {assessment['patient_id']} | "

                f"Age: {assessment['age']} | "

                f"Sex: {assessment['sex']} | "

                f"{assessment['timestamp']}"

                f"{rq_suffix}"

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

        open_child_window(
            self.root,
            AssessmentDetailWindow,
            assessment
        )


    # REPLACEMENT:
    def show_trends(self):

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

        if len(patient_records) < 2:

            messagebox.showinfo(
                "Not Enough Data",
                "At least 2 assessments are needed for longitudinal trends."
            )

            return

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
                vowel.get(
                    "F0 Range",
                    vowel.get("F0 Max", 0) - vowel.get("F0 Min", 0)
                )
            )

            pitch_var_values.append(
                vowel.get(
                    "Pitch Variability",
                    record.get("vowel_sd", {}).get("F0 Mean", 0)
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

            if "Mean Pause Duration" in ddk:

                pause_duration = ddk["Mean Pause Duration"]

            else:

                pause_speech_ratio = ddk.get(
                    "Pause/Speech Ratio",
                    0
                )

                pause_duration = (
                    DDK_DURATION * pause_speech_ratio
                    / (1 + pause_speech_ratio)
                )

            pause_values.append(
                pause_duration
            )

            pause_ratio_values.append(
                ddk.get(
                    "Pause/Speech Ratio",
                    0
                )
            )

        # Each subplot below plots metrics on genuinely different
        # scales (e.g. F0 Mean ~100-250 Hz next to F0 Range/Pitch
        # Variability, which are typically single/low-double digits).
        # Sharing one y-axis flattens the smaller-scale line into an
        # invisible flat trace at the bottom -- exactly the metrics
        # most likely to carry a meaningful clinical trend. Each
        # subplot now uses a twin axis to keep every line legible.

        fig = Figure(figsize=(14, 22))

        axes = fig.subplots(5, 1)

        fig.suptitle(
            f"Patient {patient_id} Longitudinal Trends",
            fontsize=16
        )

        def _plot_twin(ax, primary_series, secondary_series, title):

            ax2 = ax.twinx()

            lines = []

            for label, values, color in primary_series:

                line, = ax.plot(
                    visits, values, marker="o", label=label, color=color
                )

                lines.append(line)

            for label, values, color in secondary_series:

                line, = ax2.plot(
                    visits, values, marker="s", linestyle="--",
                    label=label, color=color
                )

                lines.append(line)

            ax.set_title(title, pad=15)
            ax.grid(True)

            labels = [l.get_label() for l in lines]
            ax.legend(lines, labels, loc="upper left")

            return ax2

        _plot_twin(
            axes[0],
            [("F0 Mean", f0_values, "tab:blue")],
            [
                ("F0 Range", f0_range_values, "tab:orange"),
                ("Pitch Variability", pitch_var_values, "tab:green")
            ],
            "Voice Stability"
        )

        _plot_twin(
            axes[1],
            [("HNR", hnr_values, "tab:blue")],
            [("Jitter Local", jitter_values, "tab:orange")],
            "Voice Quality"
        )

        _plot_twin(
            axes[2],
            [("DDK Rate", ddk_rate_values, "tab:blue")],
            [("DDK Regularity", ddk_reg_values, "tab:orange")],
            "Articulation"
        )

        _plot_twin(
            axes[3],
            [("Speech Rate", speech_rate_values, "tab:blue")],
            [
                ("Pause Duration", pause_values, "tab:orange"),
                ("Pause Ratio", pause_ratio_values, "tab:green")
            ],
            "Fluency"
        )

        _plot_twin(
            axes[4],
            [("F1 Mean", f1_values, "tab:blue")],
            [("F2 Mean", f2_values, "tab:orange")],
            "Resonance"
        )

        fig.tight_layout(rect=[0, 0, 1, 0.97])
        fig.subplots_adjust(hspace=0.8)

        # Embedded in its own managed Toplevel instead of plt.show(),
        # which pops a second, separate GUI event loop on top of the
        # Tkinter mainloop that's already running from main.py --
        # fragile across matplotlib versions/backends and never gets
        # cleaned up on repeated use in one session.
        open_child_window(
            self.root,
            _TrendPlotWindow,
            fig,
            f"Trends -- Patient {patient_id}"
        )