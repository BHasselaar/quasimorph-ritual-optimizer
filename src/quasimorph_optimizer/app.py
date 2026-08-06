from __future__ import annotations

import csv
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .constants import ESSENCES, TIER_RULES
from .inventory import ensure_user_inventory, load_inventory, save_inventory
from .models import Item, RitualResult
from .optimizer import OBJECTIVES, OptimizationSummary, optimize, unique_ring_order_count
from .version import __version__


class ItemDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, title: str, item: Item | None = None) -> None:
        self.item = item
        self.result_item: Item | None = None
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        ttk.Label(master, text="Name").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(master, text="Essence").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(master, text="Power").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(master, text="Stability").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(master, text="Enabled").grid(row=4, column=0, sticky="w", padx=6, pady=4)

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
        self.geometry("1450x850")
        self.minsize(1100, 650)

        self.inventory_path = ensure_user_inventory()
        self.items = load_inventory(self.inventory_path)
        self.results: list[RitualResult] = []
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()

        self._build_ui()
        self._refresh_inventory()
        self.after(100, self._poll_worker)

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        inventory_frame = ttk.Labelframe(outer, text="Inventory")
        optimizer_frame = ttk.Frame(outer)
        outer.add(inventory_frame, weight=1)
        outer.add(optimizer_frame, weight=3)

        toolbar = ttk.Frame(inventory_frame)
        toolbar.pack(fill=tk.X, padx=6, pady=6)
        for text, command in (
            ("Add", self._add_item),
            ("Edit", self._edit_item),
            ("Delete", self._delete_item),
            ("Enable/Disable", self._toggle_item),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(side=tk.LEFT, padx=2)

        filebar = ttk.Frame(inventory_frame)
        filebar.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(filebar, text="Save", command=self._save_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(filebar, text="Import CSV", command=self._import_inventory).pack(side=tk.LEFT, padx=2)
        ttk.Button(filebar, text="Export CSV", command=self._export_inventory).pack(side=tk.LEFT, padx=2)

        columns = ("enabled", "name", "essence", "power", "stability")
        self.inventory_tree = ttk.Treeview(inventory_frame, columns=columns, show="headings", selectmode="browse")
        headings = {"enabled": "Use", "name": "Name", "essence": "Essence", "power": "Power", "stability": "Stability"}
        widths = {"enabled": 45, "name": 210, "essence": 85, "power": 70, "stability": 75}
        for column in columns:
            self.inventory_tree.heading(column, text=headings[column])
            self.inventory_tree.column(column, width=widths[column], anchor=tk.CENTER if column != "name" else tk.W)
        self.inventory_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.inventory_tree.bind("<Double-1>", lambda _event: self._edit_item())

        controls = ttk.Labelframe(optimizer_frame, text="Ritual settings")
        controls.pack(fill=tk.X, padx=6, pady=(0, 8))

        self.tier_var = tk.IntVar(value=3)
        self.center_var = tk.StringVar(value="siaira")
        self.objective_var = tk.StringVar(value="sidegrade")
        self.top_n_var = tk.IntVar(value=50)
        self.flat_power_var = tk.DoubleVar(value=100.0)
        self.flat_stability_var = tk.DoubleVar(value=0.0)

        labels = ("Tier", "Center essence", "Optimize for", "Top results", "Ship Power bonus", "Ship Stability bonus")
        for index, label in enumerate(labels):
            ttk.Label(controls, text=label).grid(row=0, column=index, sticky="w", padx=5, pady=(6, 2))

        ttk.Combobox(controls, textvariable=self.tier_var, values=tuple(TIER_RULES), width=7, state="readonly").grid(row=1, column=0, padx=5, pady=(0, 6), sticky="ew")
        ttk.Combobox(controls, textvariable=self.center_var, values=ESSENCES, width=12, state="readonly").grid(row=1, column=1, padx=5, pady=(0, 6), sticky="ew")
        objective_values = tuple(OBJECTIVES)
        objective_box = ttk.Combobox(controls, textvariable=self.objective_var, values=objective_values, width=18, state="readonly")
        objective_box.grid(row=1, column=2, padx=5, pady=(0, 6), sticky="ew")
        ttk.Spinbox(controls, from_=1, to=500, textvariable=self.top_n_var, width=8).grid(row=1, column=3, padx=5, pady=(0, 6), sticky="ew")
        ttk.Entry(controls, textvariable=self.flat_power_var, width=12).grid(row=1, column=4, padx=5, pady=(0, 6), sticky="ew")
        ttk.Entry(controls, textvariable=self.flat_stability_var, width=12).grid(row=1, column=5, padx=5, pady=(0, 6), sticky="ew")


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

        result_columns = (
            "rank", "power", "stability", "power_pct", "stability_pct",
            "jackpot", "upgrade", "sidegrade", "downgrade", "disenchant", "order"
        )
        self.result_tree = ttk.Treeview(optimizer_frame, columns=result_columns, show="headings", selectmode="browse")
        result_headings = {
            "rank": "#", "power": "Power", "stability": "Stability", "power_pct": "Power %",
            "stability_pct": "Stability %", "jackpot": "Jackpot", "upgrade": "Upgrade",
            "sidegrade": "Sidegrade", "downgrade": "Downgrade", "disenchant": "Disenchant", "order": "Clockwise order"
        }
        result_widths = {"rank": 40, "power": 75, "stability": 75, "power_pct": 72, "stability_pct": 78,
                         "jackpot": 70, "upgrade": 70, "sidegrade": 75, "downgrade": 78, "disenchant": 80, "order": 480}
        for column in result_columns:
            self.result_tree.heading(column, text=result_headings[column])
            self.result_tree.column(column, width=result_widths[column], anchor=tk.CENTER if column != "order" else tk.W)
        self.result_tree.pack(fill=tk.BOTH, expand=True, padx=6)
        self.result_tree.bind("<<TreeviewSelect>>", self._show_result_details)

        details_frame = ttk.Labelframe(optimizer_frame, text="Selected ritual breakdown")
        details_frame.pack(fill=tk.BOTH, padx=6, pady=(8, 0))
        self.details_text = tk.Text(details_frame, height=10, wrap=tk.NONE, state=tk.DISABLED)
        self.details_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        footer = ttk.Label(
            self,
            text="Exact brute force using the verified community model. Ship bonuses are added after component affinity calculations.",
            anchor=tk.W,
        )
        footer.pack(fill=tk.X, padx=10, pady=(0, 6))

    def _selected_inventory_index(self) -> int | None:
        selection = self.inventory_tree.selection()
        return int(selection[0]) if selection else None

    def _refresh_inventory(self) -> None:
        self.inventory_tree.delete(*self.inventory_tree.get_children())
        for index, item in enumerate(self.items):
            self.inventory_tree.insert("", tk.END, iid=str(index), values=("✓" if item.enabled else "", item.name, item.essence, f"{item.power:g}", f"{item.stability:g}"))
        enabled = sum(item.enabled for item in self.items)
        candidates = unique_ring_order_count(enabled)
        self.status_var.set(f"{enabled} enabled items · {candidates:,} unique ring orders")

    def _add_item(self) -> None:
        dialog = ItemDialog(self, "Add inventory item")
        if dialog.result_item:
            self.items.append(dialog.result_item)
            self._refresh_inventory()
            self._save_inventory(silent=True)

    def _edit_item(self) -> None:
        index = self._selected_inventory_index()
        if index is None:
            return
        dialog = ItemDialog(self, "Edit inventory item", self.items[index])
        if dialog.result_item:
            self.items[index] = dialog.result_item
            self._refresh_inventory()
            self._save_inventory(silent=True)

    def _delete_item(self) -> None:
        index = self._selected_inventory_index()
        if index is None:
            return
        if messagebox.askyesno("Delete item", f"Delete {self.items[index].name}?"):
            del self.items[index]
            self._refresh_inventory()
            self._save_inventory(silent=True)

    def _toggle_item(self) -> None:
        index = self._selected_inventory_index()
        if index is None:
            return
        old = self.items[index]
        self.items[index] = Item(old.name, old.essence, old.power, old.stability, not old.enabled)
        self._refresh_inventory()
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
            enabled_count = sum(item.enabled for item in self.items)
            if enabled_count < 5:
                raise ValueError("Enable at least five items")
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        total = unique_ring_order_count(enabled_count)
        if total > 50_000_000 and not messagebox.askyesno(
            "Large search",
            f"This search has {total:,} unique ring orders and may take a long time. Continue?",
        ):
            return

        self.cancel_event.clear()
        self.optimize_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.progress.configure(value=0)
        self.status_var.set(f"Searching {total:,} ring orders…")

        args = {
            "items": list(self.items),
            "center_essence": self.center_var.get(),
            "tier": tier,
            "objective": self.objective_var.get(),
            "top_n": top_n,
            "flat_power_bonus": flat_power,
            "flat_stability_bonus": flat_stability,
            "progress_callback": lambda done, all_: self.worker_queue.put(("progress", (done, all_))),
            "cancel_event": self.cancel_event,
        }

        def work() -> None:
            try:
                summary = optimize(**args)
                self.worker_queue.put(("done", summary))
            except Exception as exc:  # UI boundary: display unexpected errors safely.
                self.worker_queue.put(("error", exc))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _cancel_optimization(self) -> None:
        self.cancel_event.set()
        self.status_var.set("Cancelling…")

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
            values = (
                rank,
                f"{result.total_power:.2f}",
                f"{result.total_stability:.2f}",
                f"{result.power_percent:.2%}",
                f"{result.stability_percent:.2%}",
                f"{p.jackpot:.2%}",
                f"{p.upgrade:.2%}",
                f"{p.sidegrade:.2%}",
                f"{p.downgrade:.2%}",
                f"{p.disenchant:.2%}",
                result.order_text,
            )
            self.result_tree.insert("", tk.END, iid=str(rank - 1), values=values)
        self.progress.configure(value=(summary.evaluated / summary.total_candidates * 100.0) if summary.total_candidates else 0)
        state = "Cancelled" if summary.cancelled else "Finished"
        self.status_var.set(f"{state}: {summary.evaluated:,} evaluated; {len(summary.results)} retained")
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
            f"Outcomes: Jackpot {p.jackpot:.4%} (experimental), Upgrade {p.upgrade:.4%}, Sidegrade {p.sidegrade:.4%}, Downgrade {p.downgrade:.4%}, Disenchant {p.disenchant:.4%}",
            "",
            "Per-component contributions:",
        ]
        for index, contribution in enumerate(result.contributions, start=1):
            lines.append(
                f"{index}. {contribution.item.name} [{contribution.item.essence}] — predecessor {contribution.predecessor.name}; "
                f"Power {contribution.item.power:g} × {contribution.predecessor_power_multiplier:g} × {contribution.center_power_multiplier:g} = {contribution.power:.4f}; "
                f"Stability {contribution.item.stability:g} × {contribution.predecessor_stability_multiplier:g} × {contribution.center_stability_multiplier:g} = {contribution.stability:.4f}"
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
                writer.writerow(["rank", "order", "ship_power_bonus", "ship_stability_bonus", "power", "stability", "power_target", "stability_target", "power_percent", "stability_percent", "jackpot", "upgrade", "sidegrade", "downgrade", "disenchant"])
                for rank, result in enumerate(self.results, start=1):
                    p = result.probabilities
                    writer.writerow([rank, result.order_text, result.flat_power_bonus, result.flat_stability_bonus, result.total_power, result.total_stability, result.power_target, result.stability_target, result.power_percent, result.stability_percent, p.jackpot, p.upgrade, p.sidegrade, p.downgrade, p.disenchant])
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))


def main() -> None:
    app = RitualOptimizerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
