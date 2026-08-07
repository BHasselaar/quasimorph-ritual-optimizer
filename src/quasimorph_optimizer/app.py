from __future__ import annotations

import csv
import multiprocessing
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .constants import ESSENCES, TIER_RULES
from .inventory import ensure_user_inventory, load_inventory, reset_user_inventory_to_default, save_inventory
from .models import Item, RitualResult
from .optimizer import OBJECTIVES, OptimizationSummary, optimize_parallel, unique_ring_order_count
from .settings import AppSettings, load_settings, save_settings
from .version import __version__


class ItemDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, title: str, item: Item | None = None) -> None:
        self.item = item
        self.result_item: Item | None = None
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        for row, label in enumerate(("Name", "Essence", "Power", "Stability", "Available")):
            ttk.Label(master, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)

        self.name_var = tk.StringVar(value=self.item.name if self.item else "")
        self.essence_var = tk.StringVar(value=self.item.essence if self.item else "siaira")
        self.power_var = tk.StringVar(value=f"{self.item.power:g}" if self.item else "0")
        self.stability_var = tk.StringVar(value=f"{self.item.stability:g}" if self.item else "0")
        self.enabled_var = tk.BooleanVar(value=self.item.enabled if self.item else True)

        name_entry = ttk.Entry(master, textvariable=self.name_var, width=36)
        name_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Combobox(master, textvariable=self.essence_var, values=ESSENCES, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Entry(master, textvariable=self.power_var).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Entry(master, textvariable=self.stability_var).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Checkbutton(master, variable=self.enabled_var).grid(row=4, column=1, sticky="w", padx=6, pady=4)
        master.columnconfigure(1, weight=1)
        return name_entry

    def validate(self) -> bool:
        try:
            self.result_item = Item(
                name=self.name_var.get(),
                essence=self.essence_var.get(),
                power=float(self.power_var.get()),
                stability=float(self.stability_var.get()),
                enabled=self.enabled_var.get(),
            )
            return True
        except ValueError as exc:
            messagebox.showerror("Invalid item", str(exc), parent=self)
            return False


class RitualOptimizerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"Quasimorph Ritual Optimizer v{__version__}")
        self.geometry("1550x900")
        self.minsize(1100, 650)

        self.inventory_path = ensure_user_inventory()
        self.items = load_inventory(self.inventory_path)
        self.settings = load_settings()
        self.results: list[RitualResult] = []
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._drag_source: str | None = None

        self._build_ui()
        self._refresh_inventory()
        self.after(100, self._poll_worker)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        inventory_frame = ttk.Labelframe(outer, text="Inventory — click checkbox to include/exclude; drag rows to reorder")
        optimizer_frame = ttk.Frame(outer)
        outer.add(inventory_frame, weight=1)
        outer.add(optimizer_frame, weight=3)

        toolbar = ttk.Frame(inventory_frame)
        toolbar.pack(fill=tk.X, padx=6, pady=6)
        for text, command in (("Add", self._add_item), ("Edit", self._edit_item), ("Delete", self._delete_item)):
            ttk.Button(toolbar, text=text, command=command).pack(side=tk.LEFT, padx=2)

        filebar = ttk.Frame(inventory_frame)
        filebar.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(filebar, text="Save", command=self._save_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(filebar, text="Import CSV", command=self._import_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(filebar, text="Export CSV", command=self._export_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(filebar, text="Load bundled", command=self._load_bundled_inventory).pack(side=tk.LEFT, padx=2)

        inventory_container = ttk.Frame(inventory_frame)
        inventory_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        inventory_container.rowconfigure(0, weight=1)
        inventory_container.columnconfigure(0, weight=1)

        columns = ("enabled", "name", "essence", "power", "stability")
        self.inventory_tree = ttk.Treeview(inventory_container, columns=columns, show="headings", selectmode="browse")
        headings = {
            "enabled": "Available", "name": "Name", "essence": "Essence",
            "power": "Power", "stability": "Stability"
        }
        widths = {"enabled": 75, "name": 215, "essence": 85, "power": 70, "stability": 75}
        for column in columns:
            self.inventory_tree.heading(column, text=headings[column])
            self.inventory_tree.column(
                column,
                width=widths[column],
                minwidth=45,
                stretch=column == "name",
                anchor=tk.CENTER if column != "name" else tk.W,
            )
        inventory_vscroll = ttk.Scrollbar(inventory_container, orient=tk.VERTICAL, command=self.inventory_tree.yview)
        inventory_hscroll = ttk.Scrollbar(inventory_container, orient=tk.HORIZONTAL, command=self.inventory_tree.xview)
        self.inventory_tree.configure(yscrollcommand=inventory_vscroll.set, xscrollcommand=inventory_hscroll.set)
        self.inventory_tree.grid(row=0, column=0, sticky="nsew")
        inventory_vscroll.grid(row=0, column=1, sticky="ns")
        inventory_hscroll.grid(row=1, column=0, sticky="ew")

        # Tk's Treeview has no native per-row checkbox widget, so the first column
        # behaves as a checkbox and the full row is color-coded by availability.
        self.inventory_tree.tag_configure("available", background="#dff2df", foreground="#123b12")
        self.inventory_tree.tag_configure("unavailable", background="#f3dddd", foreground="#5a1515")
        self.inventory_tree.bind("<ButtonPress-1>", self._inventory_press)
        self.inventory_tree.bind("<B1-Motion>", self._inventory_drag)
        self.inventory_tree.bind("<ButtonRelease-1>", self._inventory_release)
        self.inventory_tree.bind("<Double-1>", self._inventory_double_click)
        self.inventory_tree.bind("<space>", lambda _event: self._toggle_item())

        controls = ttk.Labelframe(optimizer_frame, text="Ritual settings")
        controls.pack(fill=tk.X, padx=6, pady=(0, 8))

        self.tier_var = tk.IntVar(value=3)
        self.center_var = tk.StringVar(value="siaira")
        self.objective_var = tk.StringVar(value="sidegrade")
        self.top_n_var = tk.IntVar(value=50)
        self.flat_power_var = tk.StringVar(value=f"{self.settings.ship_power_bonus:g}")
        self.flat_stability_var = tk.StringVar(value=f"{self.settings.ship_stability_bonus:g}")
        self.worker_count_var = tk.IntVar(value=self.settings.worker_count)

        labels = (
            "Tier", "Center essence", "Optimize for", "Top results",
            "Ship Power bonus", "Ship Stability bonus", "Workers (0 = auto)"
        )
        for index, label in enumerate(labels):
            ttk.Label(controls, text=label).grid(row=0, column=index, sticky="w", padx=5, pady=(6, 2))
            controls.columnconfigure(index, weight=1 if index in {2, 4, 5} else 0)

        ttk.Combobox(controls, textvariable=self.tier_var, values=tuple(TIER_RULES), width=7, state="readonly").grid(
            row=1, column=0, padx=5, pady=(0, 6), sticky="ew"
        )
        ttk.Combobox(controls, textvariable=self.center_var, values=ESSENCES, width=12, state="readonly").grid(
            row=1, column=1, padx=5, pady=(0, 6), sticky="ew"
        )
        ttk.Combobox(controls, textvariable=self.objective_var, values=tuple(OBJECTIVES), width=18, state="readonly").grid(
            row=1, column=2, padx=5, pady=(0, 6), sticky="ew"
        )
        ttk.Spinbox(controls, from_=1, to=500, textvariable=self.top_n_var, width=8).grid(
            row=1, column=3, padx=5, pady=(0, 6), sticky="ew"
        )
        ttk.Entry(controls, textvariable=self.flat_power_var, width=12).grid(
            row=1, column=4, padx=5, pady=(0, 6), sticky="ew"
        )
        ttk.Entry(controls, textvariable=self.flat_stability_var, width=12).grid(
            row=1, column=5, padx=5, pady=(0, 6), sticky="ew"
        )
        max_workers = max(1, os.cpu_count() or 1)
        ttk.Spinbox(controls, from_=0, to=max(64, max_workers), textvariable=self.worker_count_var, width=10).grid(
            row=1, column=6, padx=5, pady=(0, 6), sticky="ew"
        )

        self.flat_power_var.trace_add("write", self._settings_changed)
        self.flat_stability_var.trace_add("write", self._settings_changed)
        self.worker_count_var.trace_add("write", self._settings_changed)

        action_bar = ttk.Frame(optimizer_frame)
        action_bar.pack(fill=tk.X, padx=6, pady=(0, 8))
        self.optimize_button = ttk.Button(action_bar, text="Optimize", command=self._start_optimization)
        self.optimize_button.pack(side=tk.LEFT)
        self.cancel_button = ttk.Button(action_bar, text="Cancel", command=self._cancel_optimization, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=6)
        ttk.Button(action_bar, text="Export results", command=self._export_results).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(action_bar, mode="determinate", maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(action_bar, textvariable=self.status_var).pack(side=tk.RIGHT)

        result_container = ttk.Frame(optimizer_frame)
        result_container.pack(fill=tk.BOTH, expand=True, padx=6)
        result_container.rowconfigure(0, weight=1)
        result_container.columnconfigure(0, weight=1)

        result_columns = (
            "rank", "power", "stability", "power_pct", "stability_pct",
            "jackpot", "upgrade", "sidegrade", "downgrade", "disenchant", "order"
        )
        self.result_tree = ttk.Treeview(result_container, columns=result_columns, show="headings", selectmode="browse")
        result_headings = {
            "rank": "#", "power": "Power", "stability": "Stability", "power_pct": "Power %",
            "stability_pct": "Stability %", "jackpot": "Jackpot", "upgrade": "Upgrade",
            "sidegrade": "Sidegrade", "downgrade": "Downgrade", "disenchant": "Disenchant",
            "order": "Clockwise order",
        }
        result_widths = {
            "rank": 40, "power": 75, "stability": 75, "power_pct": 72, "stability_pct": 78,
            "jackpot": 70, "upgrade": 70, "sidegrade": 75, "downgrade": 78,
            "disenchant": 80, "order": 520,
        }
        for column in result_columns:
            self.result_tree.heading(column, text=result_headings[column])
            self.result_tree.column(
                column,
                width=result_widths[column],
                minwidth=40,
                stretch=column == "order",
                anchor=tk.CENTER if column != "order" else tk.W,
            )
        result_vscroll = ttk.Scrollbar(result_container, orient=tk.VERTICAL, command=self.result_tree.yview)
        result_hscroll = ttk.Scrollbar(result_container, orient=tk.HORIZONTAL, command=self.result_tree.xview)
        self.result_tree.configure(yscrollcommand=result_vscroll.set, xscrollcommand=result_hscroll.set)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        result_vscroll.grid(row=0, column=1, sticky="ns")
        result_hscroll.grid(row=1, column=0, sticky="ew")
        self.result_tree.bind("<<TreeviewSelect>>", self._show_result_details)

        details_frame = ttk.Labelframe(optimizer_frame, text="Selected ritual breakdown")
        details_frame.pack(fill=tk.BOTH, padx=6, pady=(8, 0))
        details_container = ttk.Frame(details_frame)
        details_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        details_container.rowconfigure(0, weight=1)
        details_container.columnconfigure(0, weight=1)
        self.details_text = tk.Text(details_container, height=10, wrap=tk.NONE, state=tk.DISABLED)
        details_vscroll = ttk.Scrollbar(details_container, orient=tk.VERTICAL, command=self.details_text.yview)
        details_hscroll = ttk.Scrollbar(details_container, orient=tk.HORIZONTAL, command=self.details_text.xview)
        self.details_text.configure(yscrollcommand=details_vscroll.set, xscrollcommand=details_hscroll.set)
        self.details_text.grid(row=0, column=0, sticky="nsew")
        details_vscroll.grid(row=0, column=1, sticky="ns")
        details_hscroll.grid(row=1, column=0, sticky="ew")

        cpu_count = os.cpu_count() or 1
        footer = ttk.Label(
            self,
            text=(
                "Verified community model. Ship bonuses are added after affinities. "
                f"Parallel brute force uses separate processes; auto currently resolves to {cpu_count} logical CPUs."
            ),
            anchor=tk.W,
        )
        footer.pack(fill=tk.X, padx=10, pady=(0, 6))

    def _settings_changed(self, *_args: object) -> None:
        """Persist valid values immediately whenever a settings field changes."""
        try:
            power = float(self.flat_power_var.get())
            stability = float(self.flat_stability_var.get())
            workers = max(0, int(self.worker_count_var.get()))
        except (tk.TclError, ValueError):
            return
        self.settings = AppSettings(power, stability, workers)
        try:
            save_settings(self.settings)
        except OSError:
            pass

    def _selected_inventory_index(self) -> int | None:
        selection = self.inventory_tree.selection()
        if not selection:
            return None
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _refresh_inventory(self, selected_index: int | None = None) -> None:
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        for index, item in enumerate(self.items):
            tag = "available" if item.enabled else "unavailable"
            self.inventory_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=("☑" if item.enabled else "☐", item.name, item.essence, f"{item.power:g}", f"{item.stability:g}"),
                tags=(tag,),
            )
        if selected_index is not None and 0 <= selected_index < len(self.items):
            self.inventory_tree.selection_set(str(selected_index))
            self.inventory_tree.focus(str(selected_index))
        self._update_inventory_status()

    def _update_inventory_status(self) -> None:
        enabled = sum(item.enabled for item in self.items)
        candidates = unique_ring_order_count(enabled)
        self.status_var.set(f"{enabled}/{len(self.items)} available · {candidates:,} unique ring orders")

    def _inventory_press(self, event: tk.Event) -> str | None:
        row = self.inventory_tree.identify_row(event.y)
        column = self.inventory_tree.identify_column(event.x)
        self._drag_source = None
        if not row:
            return None
        self.inventory_tree.selection_set(row)
        self.inventory_tree.focus(row)
        if column == "#1":
            self._toggle_item(int(row))
            return "break"
        self._drag_source = row
        return None

    def _inventory_drag(self, event: tk.Event) -> None:
        if self._drag_source is None:
            return
        target = self.inventory_tree.identify_row(event.y)
        if not target or target == self._drag_source:
            return
        target_index = self.inventory_tree.index(target)
        self.inventory_tree.move(self._drag_source, "", target_index)

    def _inventory_release(self, _event: tk.Event) -> None:
        if self._drag_source is None:
            return
        ordered_ids = self.inventory_tree.get_children("")
        if ordered_ids:
            old_items = list(self.items)
            self.items = [old_items[int(iid)] for iid in ordered_ids]
            moved_item = old_items[int(self._drag_source)]
            selected_index = self.items.index(moved_item)
            self._save_inventory(silent=True)
            self._refresh_inventory(selected_index)
        self._drag_source = None

    def _inventory_double_click(self, event: tk.Event) -> str | None:
        if self.inventory_tree.identify_column(event.x) == "#1":
            return "break"
        self._edit_item()
        return None

    def _add_item(self) -> None:
        dialog = ItemDialog(self, "Add inventory item")
        if dialog.result_item:
            self.items.append(dialog.result_item)
            self._refresh_inventory(len(self.items) - 1)
            self._save_inventory(silent=True)

    def _edit_item(self) -> None:
        index = self._selected_inventory_index()
        if index is None:
            return
        dialog = ItemDialog(self, "Edit inventory item", self.items[index])
        if dialog.result_item:
            self.items[index] = dialog.result_item
            self._refresh_inventory(index)
            self._save_inventory(silent=True)

    def _delete_item(self) -> None:
        index = self._selected_inventory_index()
        if index is None:
            return
        if messagebox.askyesno("Delete item", f"Delete {self.items[index].name}?"):
            del self.items[index]
            self._refresh_inventory(min(index, len(self.items) - 1))
            self._save_inventory(silent=True)

    def _toggle_item(self, index: int | None = None) -> None:
        if index is None:
            index = self._selected_inventory_index()
        if index is None:
            return
        old = self.items[index]
        self.items[index] = Item(old.name, old.essence, old.power, old.stability, not old.enabled)
        self._refresh_inventory(index)
        self._save_inventory(silent=True)

    def _save_inventory(self, silent: bool = False) -> None:
        try:
            save_inventory(self.inventory_path, self.items)
            if not silent:
                messagebox.showinfo("Inventory saved", f"Saved to:\n{self.inventory_path}")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    def _import_inventory(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not filename:
            return
        try:
            imported = load_inventory(Path(filename))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.items = imported
        self._refresh_inventory()
        self._save_inventory(silent=True)

    def _load_bundled_inventory(self) -> None:
        if not messagebox.askyesno(
            "Load bundled inventory",
            "Replace your current local inventory with the inventory bundled in v0.4.0?",
        ):
            return
        try:
            reset_user_inventory_to_default()
            self.items = load_inventory(self.inventory_path)
            self._refresh_inventory()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Load failed", str(exc))

    def _export_inventory(self) -> None:
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if filename:
            try:
                save_inventory(Path(filename), self.items)
            except OSError as exc:
                messagebox.showerror("Export failed", str(exc))

    def _start_optimization(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            tier = int(self.tier_var.get())
            top_n = int(self.top_n_var.get())
            flat_power = float(self.flat_power_var.get())
            flat_stability = float(self.flat_stability_var.get())
            requested_workers = max(0, int(self.worker_count_var.get()))
            enabled_count = sum(item.enabled for item in self.items)
            if enabled_count < 5:
                raise ValueError("Make at least five components available")
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        total = unique_ring_order_count(enabled_count)
        if total > 50_000_000 and not messagebox.askyesno(
            "Large search",
            f"This search has {total:,} unique ring orders. Continue?",
        ):
            return

        self._settings_changed()
        resolved_workers = requested_workers or (os.cpu_count() or 1)
        self.cancel_event.clear()
        self.optimize_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.progress.configure(value=0)
        self.status_var.set(f"Searching {total:,} ring orders with {resolved_workers} workers…")

        args = {
            "items": list(self.items),
            "center_essence": self.center_var.get(),
            "tier": tier,
            "objective": self.objective_var.get(),
            "top_n": top_n,
            "flat_power_bonus": flat_power,
            "flat_stability_bonus": flat_stability,
            "workers": requested_workers or None,
            "progress_callback": lambda done, all_: self.worker_queue.put(("progress", (done, all_))),
            "cancel_event": self.cancel_event,
        }

        def work() -> None:
            try:
                summary = optimize_parallel(**args)
                self.worker_queue.put(("done", summary))
            except Exception as exc:
                self.worker_queue.put(("error", exc))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel_optimization(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelling after active process chunks finish…")

    def _poll_worker(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "progress":
                    done, total = payload  # type: ignore[misc]
                    self.progress.configure(value=(done / total * 100.0) if total else 0)
                    self.status_var.set(f"Evaluated {done:,} / {total:,}")
                elif kind == "done":
                    self._finish_optimization(payload)  # type: ignore[arg-type]
                elif kind == "error":
                    self._reset_worker_buttons()
                    messagebox.showerror("Optimization failed", str(payload))
                    self.status_var.set("Failed")
        except queue.Empty:
            pass
        self.after(100, self._poll_worker)

    def _reset_worker_buttons(self) -> None:
        self.optimize_button.configure(state=tk.NORMAL)
        self.cancel_button.configure(state=tk.DISABLED)

    def _finish_optimization(self, summary: OptimizationSummary) -> None:
        self._reset_worker_buttons()
        self.results = list(summary.results)
        self.result_tree.delete(*self.result_tree.get_children())
        for rank, result in enumerate(self.results, start=1):
            p = result.probabilities
            self.result_tree.insert(
                "", tk.END, iid=str(rank - 1),
                values=(
                    rank, f"{result.total_power:.2f}", f"{result.total_stability:.2f}",
                    f"{result.power_percent:.2%}", f"{result.stability_percent:.2%}",
                    f"{p.jackpot:.2%}", f"{p.upgrade:.2%}", f"{p.sidegrade:.2%}",
                    f"{p.downgrade:.2%}", f"{p.disenchant:.2%}", result.order_text,
                ),
            )
        self.progress.configure(
            value=(summary.evaluated / summary.total_candidates * 100.0) if summary.total_candidates else 0
        )
        state = "Cancelled" if summary.cancelled else "Finished"
        self.status_var.set(
            f"{state}: {summary.evaluated:,} evaluated with {summary.workers_used} workers; "
            f"{len(summary.results)} retained"
        )
        if self.results:
            self.result_tree.selection_set("0")
            self.result_tree.focus("0")
            self._show_result_details()

    def _show_result_details(self, _event: object | None = None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        result = self.results[int(selection[0])]
        p = result.probabilities
        lines = [
            f"Clockwise order: {result.order_text}",
            "Model: verified community formulas",
            f"Ship bonuses: Power +{result.flat_power_bonus:g}, Stability +{result.flat_stability_bonus:g}",
            f"Total: Power {result.total_power:.4f}, Stability {result.total_stability:.4f}",
            f"Targets: Power {result.power_target:.4f}, Stability {result.stability_target:.4f}",
            f"Effective: Power {result.power_percent:.4%}, Stability {result.stability_percent:.4%}",
            f"Outcomes: Jackpot {p.jackpot:.4%}, Upgrade {p.upgrade:.4%}, Sidegrade {p.sidegrade:.4%}, "
            f"Downgrade {p.downgrade:.4%}, Disenchant {p.disenchant:.4%}",
            "",
            "Per-component contributions:",
        ]
        for index, contribution in enumerate(result.contributions, start=1):
            lines.append(
                f"{index}. {contribution.item.name} [{contribution.item.essence}] — "
                f"predecessor {contribution.predecessor.name}; "
                f"Power {contribution.item.power:g} × {contribution.predecessor_power_multiplier:g} × "
                f"{contribution.center_power_multiplier:g} = {contribution.power:.4f}; "
                f"Stability {contribution.item.stability:g} × {contribution.predecessor_stability_multiplier:g} × "
                f"{contribution.center_stability_multiplier:g} = {contribution.stability:.4f}"
            )
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", "\n".join(lines))
        self.details_text.configure(state=tk.DISABLED)

    def _export_results(self) -> None:
        if not self.results:
            messagebox.showinfo("No results", "Run an optimization first.")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not filename:
            return
        try:
            with Path(filename).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    "rank", "order", "ship_power_bonus", "ship_stability_bonus", "power", "stability",
                    "power_target", "stability_target", "power_percent", "stability_percent", "jackpot",
                    "upgrade", "sidegrade", "downgrade", "disenchant",
                ])
                for rank, result in enumerate(self.results, start=1):
                    p = result.probabilities
                    writer.writerow([
                        rank, result.order_text, result.flat_power_bonus, result.flat_stability_bonus,
                        result.total_power, result.total_stability, result.power_target, result.stability_target,
                        result.power_percent, result.stability_percent, p.jackpot, p.upgrade, p.sidegrade,
                        p.downgrade, p.disenchant,
                    ])
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _on_close(self) -> None:
        self._settings_changed()
        self.cancel_event.set()
        self.destroy()


def main() -> None:
    multiprocessing.freeze_support()
    app = RitualOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
