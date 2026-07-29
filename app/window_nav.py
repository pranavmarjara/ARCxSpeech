import tkinter as tk


def open_child_window(parent_window, window_cls, *args, back_text="← Back", **kwargs):
    """
    Opens `window_cls` as a new Toplevel "child" of `parent_window`.

    - Hides parent_window while the child is open (this also fixes
      duplicate windows, since the buttons that would open a second
      child live on the now-hidden parent).
    - Restores parent_window when the child is closed, whether that's
      via the injected "Back" button or the window's own [X] button.
    - If a child is already open for this parent, reuses it (brings
      it to focus) instead of opening a second one.

    window_cls is instantiated exactly as it would be normally --
    window_cls(child, *args, **kwargs) -- so no changes are needed
    inside the window class itself. The Back button is overlaid with
    place(), which works no matter whether the window internally uses
    pack() or grid() for its own widgets.

    Returns (child_toplevel, window_instance).
    """

    existing = getattr(parent_window, "_active_child", None)

    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        existing.focus_force()
        return existing, getattr(parent_window, "_active_child_instance", None)

    parent_window.withdraw()

    child = tk.Toplevel(parent_window)
    parent_window._active_child = child

    def go_back():
        child.destroy()
        parent_window._active_child = None
        parent_window._active_child_instance = None
        parent_window.deiconify()
        parent_window.lift()
        parent_window.focus_force()

    instance = window_cls(child, *args, **kwargs)
    parent_window._active_child_instance = instance

    back_btn = tk.Button(
        child,
        text=back_text,
        command=go_back,
        bg="#e0e0e0",
        relief="raised",
        cursor="hand2",
        padx=8
    )
    back_btn.place(x=10, y=10)
    back_btn.lift()

    child.protocol("WM_DELETE_WINDOW", go_back)

    return child, instance
