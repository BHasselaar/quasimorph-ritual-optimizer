from __future__ import annotations

import csv
import math
import multiprocessing
import os
import queue
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .constants import ESSENCES, TIER_RULES
from .game_data import GameDatabase, detect_game_path, load_cached_game_database, parse_resources_assets, save_game_database, localization_diagnostic_path
from .inventory import duplicate_name_index, ensure_user_inventory, load_inventory, reset_user_inventory_to_default, save_inventory
from .models import Item, RitualResult
from .optimizer import OBJECTIVES, OptimizationSummary, optimize_parallel, ritual_order_count
from .save_sync import find_session_saves, read_save
from .settings import AppSettings, load_settings, save_settings, user_data_dir
from .sprites import extract_component_sprites, sprite_cache_dir, sprite_report_path
from .sprite_investigator import investigate_item_sprite_mapping
from .version import __version__


class ItemDialog(simpledialog.Dialog):
    def __init__(self, parent, title, item: Item | None = None):
        self.item=item; self.result_item=None; super().__init__(parent,title)
    def body(self, master):
        labels=("Name","Internal ID","Essence","Power","Stability","Price","Quantity","Available")
        for r,label in enumerate(labels): ttk.Label(master,text=label).grid(row=r,column=0,sticky="w",padx=6,pady=4)
        i=self.item
        self.name=tk.StringVar(value=i.name if i else ""); self.iid=tk.StringVar(value=i.internal_id if i else "")
        self.ess=tk.StringVar(value=i.essence if i else "siaira"); self.power=tk.StringVar(value=f"{i.power:g}" if i else "0")
        self.stab=tk.StringVar(value=f"{i.stability:g}" if i else "0"); self.price=tk.StringVar(value=f"{i.price:g}" if i else "0"); self.qty=tk.StringVar(value=str(i.quantity if i else 1))
        self.enabled=tk.BooleanVar(value=i.enabled if i else True)
        e=ttk.Entry(master,textvariable=self.name,width=36); e.grid(row=0,column=1,sticky="ew",padx=6,pady=4)
        ttk.Entry(master,textvariable=self.iid).grid(row=1,column=1,sticky="ew",padx=6,pady=4)
        ttk.Combobox(master,textvariable=self.ess,values=ESSENCES,state="readonly").grid(row=2,column=1,sticky="ew",padx=6,pady=4)
        ttk.Entry(master,textvariable=self.power).grid(row=3,column=1,sticky="ew",padx=6,pady=4)
        ttk.Entry(master,textvariable=self.stab).grid(row=4,column=1,sticky="ew",padx=6,pady=4)
        ttk.Entry(master,textvariable=self.price).grid(row=5,column=1,sticky="ew",padx=6,pady=4)
        ttk.Entry(master,textvariable=self.qty).grid(row=6,column=1,sticky="ew",padx=6,pady=4)
        ttk.Checkbutton(master,variable=self.enabled).grid(row=7,column=1,sticky="w",padx=6,pady=4)
        master.columnconfigure(1,weight=1); return e
    def validate(self):
        try:
            self.result_item=Item(self.name.get(),self.ess.get(),float(self.power.get()),float(self.stab.get()),self.enabled.get(),
                                  self.iid.get(),int(self.qty.get()),self.item.max_stack if self.item else 1,
                                  self.item.sprite_path if self.item else "", float(self.price.get()))
            return True
        except ValueError as exc: messagebox.showerror("Invalid item",str(exc),parent=self); return False


class RitualOptimizerApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f"Quasimorph Ritual Optimizer v{__version__}"); self.geometry("1650x950"); self.minsize(1150,700)
        self.settings=load_settings(); self.inventory_path=ensure_user_inventory(); self.items=load_inventory(self.inventory_path)
        self.game_db=load_cached_game_database(); self.game_rules=self.game_db.rules if self.game_db else None
        self.results=[]; self._objective_results=[]; self._result_original_rank={}; self.worker=None; self.cancel_event=threading.Event()
        self.worker_queue=queue.Queue(); self._drag_source=None; self._inventory_sort_column=None; self._inventory_sort_reverse=False
        self._result_sort_column="rank"; self._result_sort_reverse=False; self._photo_cache={}
        self._build_ui(); self._refresh_inventory(); self.after(100,self._poll_worker); self.protocol("WM_DELETE_WINDOW",self._on_close)

    def _build_ui(self):
        sync=ttk.Labelframe(self,text="Game integration — read-only")
        sync.pack(fill=tk.X,padx=8,pady=(8,4))
        self.sync_var=tk.BooleanVar(value=self.settings.sync_save)
        ttk.Checkbutton(sync,text="Use save quantities and Morph Analysis bonuses",variable=self.sync_var,command=self._settings_changed).pack(side=tk.LEFT,padx=6,pady=6)
        ttk.Button(sync,text="Sync game + latest save",command=self._sync_game_and_save).pack(side=tk.LEFT,padx=4)
        ttk.Button(sync,text="Choose game folder",command=self._choose_game).pack(side=tk.LEFT,padx=4)
        ttk.Button(sync,text="Choose save",command=self._choose_save).pack(side=tk.LEFT,padx=4)
        ttk.Button(sync,text="Extract ritual sprites",command=self._start_sprite_extract).pack(side=tk.LEFT,padx=4)
        ttk.Button(sync,text="Investigate item→sprite mapping",command=self._investigate_sprite_mapping).pack(side=tk.LEFT,padx=4)
        self.sync_status=tk.StringVar(value="Manual mode")
        ttk.Label(sync,textvariable=self.sync_status).pack(side=tk.RIGHT,padx=8)

        outer=ttk.Panedwindow(self,orient=tk.HORIZONTAL); outer.pack(fill=tk.BOTH,expand=True,padx=8,pady=4)
        inv=ttk.Labelframe(outer,text="Components — checkbox include/exclude; drag to reorder"); opt=ttk.Frame(outer)
        outer.add(inv,weight=1); outer.add(opt,weight=3)

        bar=ttk.Frame(inv); bar.pack(fill=tk.X,padx=6,pady=6)
        for text,cmd in (("Add",self._add_item),("Edit",self._edit_item),("Delete",self._delete_item),("Save",self._save_inventory),("Import CSV",self._import_inventory),("Export CSV",self._export_inventory),("Load bundled",self._load_bundled_inventory)):
            ttk.Button(bar,text=text,command=cmd).pack(side=tk.LEFT,padx=2)
        sb=ttk.Frame(inv); sb.pack(fill=tk.X,padx=6,pady=(0,6)); ttk.Label(sb,text="Search").pack(side=tk.LEFT,padx=(0,5))
        self.inventory_search_var=tk.StringVar(); ttk.Entry(sb,textvariable=self.inventory_search_var).pack(side=tk.LEFT,fill=tk.X,expand=True)
        ttk.Button(sb,text="Clear",command=lambda:self.inventory_search_var.set("")).pack(side=tk.LEFT,padx=5); self.inventory_search_var.trace_add("write",lambda *_:self._refresh_inventory())

        box=ttk.Frame(inv); box.pack(fill=tk.BOTH,expand=True,padx=6,pady=(0,6)); box.rowconfigure(0,weight=1); box.columnconfigure(0,weight=1)
        cols=("enabled","name","quantity","essence","power","stability","price")
        style=ttk.Style(); style.configure("Inventory.Treeview",rowheight=68)
        self.inventory_tree=ttk.Treeview(box,columns=cols,show="tree headings",selectmode="browse",style="Inventory.Treeview")
        self.inventory_tree.heading("#0",text="Icon"); self.inventory_tree.column("#0",width=72,minwidth=72,stretch=False,anchor=tk.CENTER)
        self._inventory_headings={"enabled":"Available","name":"Name","quantity":"Qty","essence":"Essence","power":"Power","stability":"Stability","price":"Price"}
        widths={"enabled":72,"name":205,"quantity":50,"essence":82,"power":65,"stability":72,"price":70}
        for c in cols:
            self.inventory_tree.heading(c,text=self._inventory_headings[c],command=lambda x=c:self._sort_inventory(x)); self.inventory_tree.column(c,width=widths[c],anchor=tk.W if c=="name" else tk.CENTER)
        vs=ttk.Scrollbar(box,orient=tk.VERTICAL,command=self.inventory_tree.yview); hs=ttk.Scrollbar(box,orient=tk.HORIZONTAL,command=self.inventory_tree.xview)
        self.inventory_tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set); self.inventory_tree.grid(row=0,column=0,sticky="nsew"); vs.grid(row=0,column=1,sticky="ns"); hs.grid(row=1,column=0,sticky="ew")
        self.inventory_tree.tag_configure("available",background="#dff2df",foreground="#123b12"); self.inventory_tree.tag_configure("unavailable",background="#f3dddd",foreground="#5a1515")
        self.inventory_tree.bind("<ButtonPress-1>",self._inventory_press); self.inventory_tree.bind("<B1-Motion>",self._inventory_drag); self.inventory_tree.bind("<ButtonRelease-1>",self._inventory_release); self.inventory_tree.bind("<Double-1>",self._inventory_double_click)

        controls=ttk.Labelframe(opt,text="Ritual settings"); controls.pack(fill=tk.X,padx=6,pady=(0,8))
        self.tier_var=tk.IntVar(value=1); self.center_var=tk.StringVar(value="eon"); self.objective_var=tk.StringVar(value="balanced"); self.top_n_var=tk.IntVar(value=10000)
        self.flat_power_var=tk.StringVar(value=f"{self.settings.ship_power_bonus:g}"); self.flat_stability_var=tk.StringVar(value=f"{self.settings.ship_stability_bonus:g}"); self.worker_count_var=tk.IntVar(value=self.settings.worker_count)
        labels=("Tier","Center essence","Optimize for","Top results","Ship Power bonus","Ship Stability bonus","Workers (0=auto)")
        for i,label in enumerate(labels): ttk.Label(controls,text=label).grid(row=0,column=i,sticky="w",padx=5,pady=(6,2))
        ttk.Combobox(controls,textvariable=self.tier_var,values=tuple(TIER_RULES),state="readonly",width=6).grid(row=1,column=0,padx=5,pady=(0,6))
        ttk.Combobox(controls,textvariable=self.center_var,values=ESSENCES,state="readonly",width=11).grid(row=1,column=1,padx=5,pady=(0,6))
        ttk.Combobox(controls,textvariable=self.objective_var,values=tuple(OBJECTIVES),state="readonly",width=16).grid(row=1,column=2,padx=5,pady=(0,6))
        ttk.Spinbox(controls,from_=1,to=100000,textvariable=self.top_n_var,width=9).grid(row=1,column=3,padx=5,pady=(0,6))
        ttk.Entry(controls,textvariable=self.flat_power_var,width=11).grid(row=1,column=4,padx=5,pady=(0,6)); ttk.Entry(controls,textvariable=self.flat_stability_var,width=11).grid(row=1,column=5,padx=5,pady=(0,6)); ttk.Spinbox(controls,from_=0,to=128,textvariable=self.worker_count_var,width=9).grid(row=1,column=6,padx=5,pady=(0,6))
        self.allow_repeats_var=tk.BooleanVar(value=False)
        ttk.Checkbutton(controls,text="Allow repeated components (advanced)",variable=self.allow_repeats_var).grid(row=2,column=0,columnspan=4,sticky="w",padx=5,pady=(0,6))
        ttk.Label(controls,text="Default uses each component type at most once; save quantities are still shown.").grid(row=2,column=4,columnspan=3,sticky="w",padx=5,pady=(0,6))
        for v in (self.flat_power_var,self.flat_stability_var): v.trace_add("write",lambda *_:self._settings_changed())
        self.worker_count_var.trace_add("write",lambda *_:self._settings_changed())

        act=ttk.Frame(opt); act.pack(fill=tk.X,padx=6,pady=(0,8)); self.optimize_button=ttk.Button(act,text="Optimize",command=self._start_optimization); self.optimize_button.pack(side=tk.LEFT)
        self.cancel_button=ttk.Button(act,text="Cancel",command=self._cancel_optimization,state=tk.DISABLED); self.cancel_button.pack(side=tk.LEFT,padx=6); ttk.Button(act,text="Export results",command=self._export_results).pack(side=tk.LEFT)
        self.progress=ttk.Progressbar(act,mode="determinate",maximum=100); self.progress.pack(side=tk.LEFT,fill=tk.X,expand=True,padx=10); self.status_var=tk.StringVar(value="Ready"); ttk.Label(act,textvariable=self.status_var).pack(side=tk.RIGHT)

        rb=ttk.Frame(opt); rb.pack(fill=tk.BOTH,expand=True,padx=6); rb.rowconfigure(0,weight=1); rb.columnconfigure(0,weight=1)
        rcols=("rank","cost","power","stability","power_pct","stability_pct","jackpot","upgrade","sidegrade","downgrade","disenchant","order")
        self.result_tree=ttk.Treeview(rb,columns=rcols,show="headings",selectmode="browse"); self._result_headings={"rank":"#","cost":"Cost","power":"Power","stability":"Stability","power_pct":"Power %","stability_pct":"Stability %","jackpot":"Jackpot","upgrade":"Upgrade","sidegrade":"Sidegrade","downgrade":"Downgrade","disenchant":"Disenchant","order":"Clockwise order"}
        widths={"rank":42,"cost":70,"power":70,"stability":72,"power_pct":72,"stability_pct":78,"jackpot":68,"upgrade":68,"sidegrade":72,"downgrade":76,"disenchant":80,"order":500}
        for c in rcols: self.result_tree.heading(c,text=self._result_headings[c],command=lambda x=c:self._sort_results(x)); self.result_tree.column(c,width=widths[c],anchor=tk.W if c=="order" else tk.CENTER)
        rvs=ttk.Scrollbar(rb,orient=tk.VERTICAL,command=self.result_tree.yview); rhs=ttk.Scrollbar(rb,orient=tk.HORIZONTAL,command=self.result_tree.xview); self.result_tree.configure(yscrollcommand=rvs.set,xscrollcommand=rhs.set); self.result_tree.grid(row=0,column=0,sticky="nsew"); rvs.grid(row=0,column=1,sticky="ns"); rhs.grid(row=1,column=0,sticky="ew"); self.result_tree.bind("<<TreeviewSelect>>",self._show_result_details)

        detail=ttk.Panedwindow(opt,orient=tk.HORIZONTAL); detail.pack(fill=tk.BOTH,padx=6,pady=(8,0))
        graph=ttk.Labelframe(detail,text="Ritual preview"); textf=ttk.Labelframe(detail,text="Selected ritual breakdown"); detail.add(graph,weight=1); detail.add(textf,weight=2)
        self.ritual_canvas=tk.Canvas(graph,height=245,bg="#202020",highlightthickness=0); self.ritual_canvas.pack(fill=tk.BOTH,expand=True,padx=4,pady=4)
        tb=ttk.Frame(textf); tb.pack(fill=tk.BOTH,expand=True); self.details_text=tk.Text(tb,height=12,wrap=tk.NONE,state=tk.DISABLED); tv=ttk.Scrollbar(tb,orient=tk.VERTICAL,command=self.details_text.yview); th=ttk.Scrollbar(tb,orient=tk.HORIZONTAL,command=self.details_text.xview); self.details_text.configure(yscrollcommand=tv.set,xscrollcommand=th.set); self.details_text.grid(row=0,column=0,sticky="nsew"); tv.grid(row=0,column=1,sticky="ns"); th.grid(row=1,column=0,sticky="ew"); tb.rowconfigure(0,weight=1); tb.columnconfigure(0,weight=1)

    def _settings_changed(self,*_):
        try: p=float(self.flat_power_var.get()); s=float(self.flat_stability_var.get()); w=max(0,int(self.worker_count_var.get()))
        except (ValueError,tk.TclError,AttributeError): return
        self.settings=AppSettings(p,s,w,bool(self.sync_var.get()),self.settings.game_path,self.settings.save_path); save_settings(self.settings)

    def _photo(self,path):
        if not path or not Path(path).exists(): return None
        if path not in self._photo_cache:
            try:
                img=tk.PhotoImage(file=path)
                max_w,max_h=60,60
                w,h=max(1,img.width()),max(1,img.height())

                # Shrink oversized images until BOTH dimensions fit.
                shrink=max(1,math.ceil(w/max_w),math.ceil(h/max_h))
                if shrink>1:
                    img=img.subsample(shrink,shrink)
                    w,h=max(1,img.width()),max(1,img.height())

                # Enlarge small sprites while preserving aspect ratio. Limit
                # integer zoom to keep pixel art crisp.
                grow=max(1,min(max_w//w,max_h//h,3))
                if grow>1:
                    img=img.zoom(grow,grow)

                self._photo_cache[path]=img
            except tk.TclError:
                self._photo_cache[path]=None
        return self._photo_cache[path]

    def _refresh_inventory(self,selected_index=None):
        self.inventory_tree.delete(*self.inventory_tree.get_children()); query=self.inventory_search_var.get().strip().casefold() if hasattr(self,"inventory_search_var") else ""
        indices=list(range(len(self.items)))
        if self._inventory_sort_column:
            c=self._inventory_sort_column
            def key(i):
                x=self.items[i]; return {"enabled":x.enabled,"name":x.name.casefold(),"quantity":x.quantity,"essence":x.essence,"power":x.power,"stability":x.stability,"price":x.price}[c]
            indices.sort(key=key,reverse=self._inventory_sort_reverse)
        for idx in indices:
            x=self.items[idx]
            if query and query not in x.name.casefold() and query not in x.internal_id.casefold(): continue
            available=x.enabled and x.quantity>0
            row_kwargs={"iid":str(idx),"values":("☑" if x.enabled else "☐",x.name,x.quantity,x.essence,f"{x.power:g}",f"{x.stability:g}",f"{x.price:g}"),"tags":("available" if available else "unavailable",)}
            photo=self._photo(x.sprite_path)
            if photo is not None: row_kwargs["image"]=photo
            self.inventory_tree.insert("",tk.END,**row_kwargs)
        self._update_inventory_status()

    def _sort_inventory(self,column):
        if self._inventory_sort_column==column:self._inventory_sort_reverse=not self._inventory_sort_reverse
        else:self._inventory_sort_column=column;self._inventory_sort_reverse=column not in {"name","essence"}
        self._refresh_inventory()
        for c,t in self._inventory_headings.items(): self.inventory_tree.heading(c,text=t+(" ▼" if c==column and self._inventory_sort_reverse else " ▲" if c==column else ""),command=lambda x=c:self._sort_inventory(x))
    def _update_inventory_status(self):
        active=[i for i in self.items if i.enabled and i.quantity>0]; units=sum(i.quantity for i in active); self.status_var.set(f"{len(active)} available component types · {units} units")
    def _selected_inventory_index(self):
        sel=self.inventory_tree.selection(); return int(sel[0]) if sel else None
    def _inventory_press(self,event):
        row=self.inventory_tree.identify_row(event.y); col=self.inventory_tree.identify_column(event.x)
        if row and col=="#1": self._toggle_item(int(row)); return "break"
        self._drag_source=row or None; return None
    def _inventory_drag(self,event):
        if not self._drag_source or self._inventory_sort_column or self.inventory_search_var.get(): return
        target=self.inventory_tree.identify_row(event.y)
        if target and target!=self._drag_source:self.inventory_tree.move(self._drag_source,"",self.inventory_tree.index(target))
    def _inventory_release(self,_event):
        if self._drag_source and not self._inventory_sort_column and not self.inventory_search_var.get():
            order=[int(x) for x in self.inventory_tree.get_children()]; self.items=[self.items[i] for i in order]; self._save_inventory(silent=True); self._refresh_inventory()
        self._drag_source=None
    def _inventory_double_click(self,event):
        if self.inventory_tree.identify_column(event.x)!="#1": self._edit_item()
    def _toggle_item(self,index=None):
        index=self._selected_inventory_index() if index is None else index
        if index is None:return
        x=self.items[index]; qty=x.quantity if x.quantity>0 else 1; self.items[index]=replace(x,enabled=not x.enabled,quantity=qty); self._save_inventory(silent=True); self._refresh_inventory(index)
    def _add_item(self):
        d=ItemDialog(self,"Add component");
        if d.result_item:
            if duplicate_name_index(self.items,d.result_item.name) is not None: messagebox.showerror("Duplicate component","A component with that name already exists."); return
            self.items.append(d.result_item); self._save_inventory(silent=True); self._refresh_inventory()
    def _edit_item(self):
        idx=self._selected_inventory_index();
        if idx is None:return
        d=ItemDialog(self,"Edit component",self.items[idx])
        if d.result_item:
            if duplicate_name_index(self.items,d.result_item.name,idx) is not None: messagebox.showerror("Duplicate component","A component with that name already exists."); return
            self.items[idx]=d.result_item; self._save_inventory(silent=True); self._refresh_inventory(idx)
    def _delete_item(self):
        idx=self._selected_inventory_index();
        if idx is not None and messagebox.askyesno("Delete component",f"Delete {self.items[idx].name}?"): del self.items[idx]; self._save_inventory(silent=True); self._refresh_inventory()
    def _save_inventory(self,silent=False):
        try: save_inventory(self.inventory_path,self.items); (not silent) and messagebox.showinfo("Inventory saved",str(self.inventory_path))
        except OSError as exc: messagebox.showerror("Save failed",str(exc))
    def _import_inventory(self):
        f=filedialog.askopenfilename(filetypes=[("CSV","*.csv")]);
        if f:
            try:self.items=load_inventory(Path(f));self._save_inventory(silent=True);self._refresh_inventory()
            except Exception as exc:messagebox.showerror("Import failed",str(exc))
    def _export_inventory(self):
        f=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")]);
        if f: save_inventory(Path(f),self.items)
    def _load_bundled_inventory(self):
        if messagebox.askyesno("Load bundled inventory","Replace the local inventory with the bundled manual list?"): self.inventory_path=reset_user_inventory_to_default();self.items=load_inventory(self.inventory_path);self._refresh_inventory()

    def _choose_game(self):
        d=filedialog.askdirectory(title="Select Quasimorph installation folder",initialdir=self.settings.game_path or None)
        if d:self.settings.game_path=d;save_settings(self.settings);self.sync_status.set(f"Game: {d}")
    def _choose_save(self):
        f=filedialog.askopenfilename(title="Select slot_*_session.dat",filetypes=[("Quasimorph session","slot_*_session.dat"),("DAT","*.dat")])
        if f:self.settings.save_path=f;save_settings(self.settings);self.sync_status.set(f"Save: {Path(f).name}")
    def _sync_game_and_save(self):
        try:
            game=detect_game_path(self.settings.game_path)
            if not game:
                self._choose_game(); game=detect_game_path(self.settings.game_path)
            if not game: raise RuntimeError("Quasimorph installation was not found")
            self.sync_status.set("Reading game database…"); self.update_idletasks()
            db=parse_resources_assets(game/"Quasimorph_Data"/"resources.assets"); save_game_database(db); self.game_db=db; self.game_rules=db.rules
            save_path=Path(self.settings.save_path) if self.settings.save_path and Path(self.settings.save_path).exists() else (find_session_saves()[0] if find_session_saves() else None)
            snapshot=read_save(save_path) if save_path else None
            cache=sprite_cache_dir(); new=[]
            for base in db.items:
                qty=snapshot.quantities.get(base.internal_id,0) if snapshot else 0; spr=cache/f"{base.internal_id}.png"
                new.append(replace(base,quantity=qty,enabled=qty>0,sprite_path=str(spr) if spr.exists() else ""))
            self.items=new; self.inventory_path=user_data_dir()/"inventory.csv"; self._save_inventory(silent=True)
            self.settings.game_path=str(game); self.settings.save_path=str(save_path) if save_path else ""; self.sync_var.set(bool(snapshot))
            if snapshot:self.flat_power_var.set(f"{snapshot.power_bonus:g}");self.flat_stability_var.set(f"{snapshot.stability_bonus:g}")
            self._settings_changed(); self._photo_cache.clear(); self._refresh_inventory()
            loc_diag=localization_diagnostic_path()
            self.sync_status.set(
                f"Imported {len(new)} ritual components · exact localization"
                +(f" · {save_path.name}" if save_path else "")
                +(f" · localization: {loc_diag.name}" if loc_diag.exists() else "")
            )
        except Exception as exc:messagebox.showerror("Game sync failed",str(exc));self.sync_status.set("Sync failed")
    def _investigate_sprite_mapping(self):
        game=detect_game_path(self.settings.game_path)
        if not game:
            messagebox.showerror(
                "Game not found",
                "Choose or sync the Quasimorph game folder first."
            )
            return

        self.sync_status.set("Investigating item→sprite mapping…")

        def work():
            try:
                result=investigate_item_sprite_mapping(game)
                self.worker_queue.put(("sprite_investigation_done",result))
            except Exception as exc:
                self.worker_queue.put(("sprite_investigation_error",exc))

        threading.Thread(target=work,daemon=True).start()

    def _start_sprite_extract(self):
        game=detect_game_path(self.settings.game_path)
        if not game: messagebox.showerror("Game not found","Choose or sync the Quasimorph game folder first.");return
        self.sync_status.set("Extracting ritual sprites…")
        def work():
            try:self.worker_queue.put(("sprites_done",extract_component_sprites(game,[x for x in self.items if x.internal_id])))
            except Exception as exc:self.worker_queue.put(("sprites_error",exc))
        threading.Thread(target=work,daemon=True).start()

    def _start_optimization(self):
        if self.worker and self.worker.is_alive():return
        try:
            tier=int(self.tier_var.get());top=int(self.top_n_var.get());p=float(self.flat_power_var.get());s=float(self.flat_stability_var.get());workers=max(0,int(self.worker_count_var.get()))
            total=ritual_order_count(self.items,self.allow_repeats_var.get())
            if total<=0: raise ValueError("At least five available component units are required")
        except Exception as exc:messagebox.showerror("Invalid settings",str(exc));return
        if total>100_000_000 and not messagebox.askyesno("Large search",f"This exact search has {total:,} unique circular rituals. Continue?"):return
        self._settings_changed();self.cancel_event.clear();self.optimize_button.configure(state=tk.DISABLED);self.cancel_button.configure(state=tk.NORMAL);self.progress.configure(value=0);self.status_var.set(f"Searching {total:,} unique rituals…")
        args=dict(items=list(self.items),center_essence=self.center_var.get(),tier=tier,objective=self.objective_var.get(),top_n=top,flat_power_bonus=p,flat_stability_bonus=s,workers=workers or None,game_rules=self.game_rules,allow_repeats=self.allow_repeats_var.get(),progress_callback=lambda d,t:self.worker_queue.put(("progress",(d,t))),cancel_event=self.cancel_event)
        def work():
            try:self.worker_queue.put(("done",optimize_parallel(**args)))
            except Exception as exc:self.worker_queue.put(("error",exc))
        self.worker=threading.Thread(target=work,daemon=True);self.worker.start()
    def _cancel_optimization(self):self.cancel_event.set();self.status_var.set("Cancelling…")
    def _poll_worker(self):
        try:
            while True:
                kind,payload=self.worker_queue.get_nowait()
                if kind=="progress":d,t=payload;self.progress.configure(value=d/t*100 if t else 0);self.status_var.set(f"Evaluated {d:,} / {t:,}")
                elif kind=="done":self._finish_optimization(payload)
                elif kind=="error":self._reset_worker_buttons();messagebox.showerror("Optimization failed",str(payload));self.status_var.set("Failed")
                elif kind=="sprite_investigation_done":
                    info=payload
                    top=info.get("top_candidate","")
                    if info.get("controls_establish_serialized_mapping"):
                        msg=f"Sprite mapping investigated · {info.get('candidate_count',0)} target candidates"
                        if top: msg+=f" · top: {top}"
                    else:
                        msg="Sprite mapping investigated · association appears runtime/code-driven"
                    self.sync_status.set(msg)
                    try:
                        os.startfile(info["index_html"])
                    except Exception:
                        pass
                elif kind=="sprite_investigation_error":
                    messagebox.showerror("Sprite mapping investigation failed",str(payload))
                    self.sync_status.set("Sprite mapping investigation failed")
                elif kind=="sprites_done":
                    mapping=payload
                    self.items=[replace(x,sprite_path=mapping.get(x.internal_id,x.sprite_path)) for x in self.items]
                    self._save_inventory(silent=True)
                    self._photo_cache.clear()
                    self._refresh_inventory()
                    report_path=sprite_report_path()
                    self.sync_status.set(f"Extracted {len(mapping)} ritual sprites · report: {report_path.name}")
                elif kind=="sprites_error":messagebox.showerror("Sprite extraction failed",str(payload));self.sync_status.set("Sprite extraction failed")
        except queue.Empty:pass
        self.after(100,self._poll_worker)
    def _reset_worker_buttons(self):self.optimize_button.configure(state=tk.NORMAL);self.cancel_button.configure(state=tk.DISABLED)
    def _finish_optimization(self,summary:OptimizationSummary):
        self._reset_worker_buttons();self._objective_results=list(summary.results);self._result_original_rank={id(r):i for i,r in enumerate(self._objective_results,1)};self.results=list(self._objective_results);self._render_results();self.progress.configure(value=summary.evaluated/summary.total_candidates*100 if summary.total_candidates else 0);self.status_var.set(f"Finished: {summary.evaluated:,} exact rituals · {summary.backend} · {summary.workers_used} workers · {len(summary.results):,} retained")
        if self.results:self.result_tree.selection_set("0");self._show_result_details()
    def _render_results(self):
        self.result_tree.delete(*self.result_tree.get_children())
        for row,r in enumerate(self.results):
            p=r.probabilities;self.result_tree.insert("",tk.END,iid=str(row),values=(self._result_original_rank.get(id(r),row+1),f"{r.total_price:.0f}",f"{r.total_power:.2f}",f"{r.total_stability:.2f}",f"{r.power_percent:.2%}",f"{r.stability_percent:.2%}",f"{p.jackpot:.2%}",f"{p.upgrade:.2%}",f"{p.sidegrade:.2%}",f"{p.downgrade:.2%}",f"{p.disenchant:.2%}",r.order_text))
    def _sort_results(self,column):
        if not self.results:return
        if self._result_sort_column==column:self._result_sort_reverse=not self._result_sort_reverse
        else:self._result_sort_column=column;self._result_sort_reverse=column not in {"rank","order"}
        def val(r):
            p=r.probabilities;return {"rank":self._result_original_rank.get(id(r),10**9),"cost":r.total_price,"power":r.total_power,"stability":r.total_stability,"power_pct":r.power_percent,"stability_pct":r.stability_percent,"jackpot":p.jackpot,"upgrade":p.upgrade,"sidegrade":p.sidegrade,"downgrade":p.downgrade,"disenchant":p.disenchant,"order":r.order_text.casefold()}[column]
        self.results.sort(key=val,reverse=self._result_sort_reverse);self._render_results()
    def _show_result_details(self,_event=None):
        sel=self.result_tree.selection();
        if not sel:return
        r=self.results[int(sel[0])];p=r.probabilities;lines=[f"Clockwise order: {r.order_text}",f"Material cost: {r.total_price:g}",f"Ship bonuses: Power +{r.flat_power_bonus:g}, Stability +{r.flat_stability_bonus:g}",f"Total: Power {r.total_power:.4f}, Stability {r.total_stability:.4f}",f"Targets: Power {r.power_target:.4f}, Stability {r.stability_target:.4f}",f"Effective: Power {r.power_percent:.4%}, Stability {r.stability_percent:.4%}",f"Outcomes: Jackpot {p.jackpot:.4%}, Upgrade {p.upgrade:.4%}, Sidegrade {p.sidegrade:.4%}, Downgrade {p.downgrade:.4%}, Disenchant {p.disenchant:.4%}","","Per-component contributions:"]
        for i,c in enumerate(r.contributions,1):lines.append(f"{i}. {c.item.name} [{c.item.essence}] — predecessor {c.predecessor.name}; Power {c.item.power:g} × {c.predecessor_power_multiplier:g} × {c.center_power_multiplier:g} = {c.power:.4f}; Stability {c.item.stability:g} × {c.predecessor_stability_multiplier:g} × {c.center_stability_multiplier:g} = {c.stability:.4f}")
        self.details_text.configure(state=tk.NORMAL);self.details_text.delete("1.0",tk.END);self.details_text.insert("1.0","\n".join(lines));self.details_text.configure(state=tk.DISABLED);self._draw_ritual(r)
    def _draw_ritual(self,r):
        c=self.ritual_canvas;c.delete("all");w=max(c.winfo_width(),360);h=max(c.winfo_height(),230);cx=w/2;cy=h/2;rad=min(w,h)*0.34
        pts=[]
        import math
        for i in range(5):
            a=-math.pi/2+i*2*math.pi/5;pts.append((cx+rad*math.cos(a),cy+rad*math.sin(a)))
        for i,(x,y) in enumerate(pts):
            nx,ny=pts[(i+1)%5];c.create_line(x,y,nx,ny,fill="#888",width=2,arrow=tk.LAST)
        c.create_oval(cx-42,cy-28,cx+42,cy+28,fill="#333",outline="#bbb");c.create_text(cx,cy-5,text=self.center_var.get().upper(),fill="white",font=("Segoe UI",10,"bold"));c.create_text(cx,cy+12,text=f"Tier {self.tier_var.get()}",fill="#ddd")
        for item,(x,y) in zip(r.order,pts):
            img=self._photo(item.sprite_path)
            if img:c.create_image(x,y-8,image=img)
            else:c.create_rectangle(x-18,y-26,x+18,y+10,fill="#444",outline="#aaa")
            c.create_text(x,y+24,text=item.name,width=110,fill="white",font=("Segoe UI",8))
    def _export_results(self):
        if not self.results:return
        f=filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")]);
        if not f:return
        with Path(f).open("w",encoding="utf-8",newline="") as h:
            w=csv.writer(h);w.writerow(["rank","order","cost","power","stability","power_percent","stability_percent","jackpot","upgrade","sidegrade","downgrade","disenchant"])
            for i,r in enumerate(self.results,1):p=r.probabilities;w.writerow([i,r.order_text,r.total_price,r.total_power,r.total_stability,r.power_percent,r.stability_percent,p.jackpot,p.upgrade,p.sidegrade,p.downgrade,p.disenchant])
    def _on_close(self):self._settings_changed();self.cancel_event.set();self.destroy()


def main():
    multiprocessing.freeze_support();RitualOptimizerApp().mainloop()
if __name__=="__main__":main()
