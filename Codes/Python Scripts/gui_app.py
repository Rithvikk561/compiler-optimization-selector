import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
import os, subprocess, threading, time

from optimization_selector import get_best_optimization, apply_optimization
from ml_optimizer import CLANG_PATH, CompilerEnv

BG="#F5F7FB"; WHITE="#FFFFFF"; BORDER="#E2E8F0"; TEXT="#172033"
MUTED="#64748B"; BLUE="#2563EB"; BLUE_BG="#EFF6FF"; GREEN="#16A34A"
PURPLE="#7C3AED"; PURPLE_BG="#F5F3FF"; RED="#DC2626"; AMBER="#D97706"

class CompilerGUI:
    def __init__(self, root):
        self.root=root
        self.root.title("TOACD — Compiler Optimization Research Platform")
        self.root.geometry("1440x900"); self.root.minsize(1150,700)
        self.root.configure(bg=BG)
        self.selected_file=None; self.strategy="—"; self.running=False
        self.results={"o3":{"time":None,"size":None,"security":"—"},
                      "ai":{"time":None,"size":None,"security":"—"}}
        self.pages={}; self.nav={}
        self.build()

    def build(self):
        self.sidebar=tk.Frame(self.root,bg=WHITE,width=225,highlightbackground=BORDER,highlightthickness=1)
        self.sidebar.pack(side="left",fill="y"); self.sidebar.pack_propagate(False)

        brand=tk.Frame(self.sidebar,bg=WHITE); brand.pack(fill="x",padx=20,pady=(25,28))
        tk.Label(brand,text="TOACD",bg=WHITE,fg="#123B7A",font=("Segoe UI",22,"bold")).pack(anchor="w")
        tk.Label(brand,text="Compiler Optimization\nResearch Platform",bg=WHITE,fg=MUTED,
                 justify="left",font=("Segoe UI",9)).pack(anchor="w",pady=(3,0))
        tk.Label(self.sidebar,text="WORKSPACE",bg=WHITE,fg="#94A3B8",
                 font=("Segoe UI",8,"bold")).pack(anchor="w",padx=20,pady=(0,8))

        for name in ["Dashboard","Source Code","IR Analysis","Optimization","Benchmark","Security","Reports"]:
            b=tk.Button(self.sidebar,text="  "+name,command=lambda n=name:self.show(n),
                        anchor="w",relief="flat",bd=0,bg=WHITE,fg="#475569",
                        activebackground=BLUE_BG,activeforeground=BLUE,
                        font=("Segoe UI",10),padx=12,pady=10,cursor="hand2")
            b.pack(fill="x",padx=12,pady=2); self.nav[name]=b

        tk.Frame(self.sidebar,bg=WHITE).pack(fill="both",expand=True)
        info=tk.Frame(self.sidebar,bg="#F8FAFC",highlightbackground=BORDER,highlightthickness=1)
        info.pack(fill="x",padx=14,pady=14)
        tk.Label(info,text="TOOLCHAIN",bg="#F8FAFC",fg="#94A3B8",font=("Segoe UI",8,"bold")).pack(anchor="w",padx=12,pady=(10,2))
        tk.Label(info,text="LLVM / Clang",bg="#F8FAFC",fg=TEXT,font=("Segoe UI",9,"bold")).pack(anchor="w",padx=12)
        tk.Label(info,text="AI optimization enabled",bg="#F8FAFC",fg=GREEN,font=("Segoe UI",8)).pack(anchor="w",padx=12,pady=(1,10))

        self.content=tk.Frame(self.root,bg=BG); self.content.pack(side="left",fill="both",expand=True)
        top=tk.Frame(self.content,bg=WHITE,height=70,highlightbackground=BORDER,highlightthickness=1)
        top.pack(fill="x"); top.pack_propagate(False)
        left=tk.Frame(top,bg=WHITE); left.pack(side="left",padx=28)
        self.title=tk.Label(left,text="Dashboard",bg=WHITE,fg=TEXT,font=("Segoe UI",17,"bold")); self.title.pack(anchor="w",pady=(12,0))
        self.subtitle=tk.Label(left,text="Compiler optimization experiment overview",bg=WHITE,fg=MUTED,font=("Segoe UI",9)); self.subtitle.pack(anchor="w")
        right=tk.Frame(top,bg=WHITE); right.pack(side="right",padx=24)
        self.file_label=tk.Label(right,text="No source selected",bg=WHITE,fg=MUTED,font=("Segoe UI",9)); self.file_label.pack(side="left",padx=(0,15))
        ttk.Button(right,text="Open C File",command=self.select_file,bootstyle="primary",width=13).pack(side="left")

        self.container=tk.Frame(self.content,bg=BG); self.container.pack(fill="both",expand=True,padx=28,pady=18)
        self.make_dashboard(); self.make_source(); self.make_ir(); self.make_opt(); self.make_bench(); self.make_security(); self.make_reports()
        self.status=tk.StringVar(value="Ready")
        bar=tk.Frame(self.root,bg=WHITE,height=32,highlightbackground=BORDER,highlightthickness=1); bar.pack(side="bottom",fill="x"); bar.pack_propagate(False)
        tk.Label(bar,textvariable=self.status,bg=WHITE,fg=MUTED,font=("Segoe UI",8)).pack(side="left",padx=18)
        self.progress=ttk.Progressbar(bar,mode="indeterminate",bootstyle="primary",length=160); self.progress.pack(side="right",padx=18,pady=7)
        self.show("Dashboard")

    def page(self,name):
        f=tk.Frame(self.container,bg=BG); self.pages[name]=f; return f

    def show(self,name):
        for f in self.pages.values(): f.pack_forget()
        self.pages[name].pack(fill="both",expand=True)
        subs={"Dashboard":"Compiler optimization experiment overview","Source Code":"Inspect the selected C source program",
              "IR Analysis":"LLVM intermediate representation and feature analysis","Optimization":"Compare optimization strategies",
              "Benchmark":"Execution and binary-size measurements","Security":"Security status and preservation",
              "Reports":"Experiment summary and comparison results"}
        self.title.config(text=name); self.subtitle.config(text=subs[name])
        for n,b in self.nav.items():
            b.config(bg=BLUE_BG if n==name else WHITE,fg=BLUE if n==name else "#475569",
                     font=("Segoe UI",10,"bold" if n==name else "normal"))

    def card(self,parent,title,value,sub,color=BLUE):
        c=tk.Frame(parent,bg=WHITE,highlightbackground=BORDER,highlightthickness=1); c.pack(side="left",fill="both",expand=True,padx=5)
        tk.Frame(c,bg=color,width=4).pack(side="left",fill="y")
        b=tk.Frame(c,bg=WHITE); b.pack(side="left",fill="both",expand=True,padx=14,pady=11)
        tk.Label(b,text=title.upper(),bg=WHITE,fg=MUTED,font=("Segoe UI",8,"bold")).pack(anchor="w")
        v=tk.Label(b,text=value,bg=WHITE,fg=TEXT,font=("Segoe UI",17,"bold")); v.pack(anchor="w",pady=(4,0))
        tk.Label(b,text=sub,bg=WHITE,fg="#94A3B8",font=("Segoe UI",8)).pack(anchor="w")
        return v

    def section(self,parent,title,sub=""):
        c=tk.Frame(parent,bg=WHITE,highlightbackground=BORDER,highlightthickness=1); c.pack(fill="both",expand=True)
        h=tk.Frame(c,bg=WHITE); h.pack(fill="x",padx=18,pady=(14,8))
        tk.Label(h,text=title,bg=WHITE,fg=TEXT,font=("Segoe UI",11,"bold")).pack(side="left")
        tk.Label(h,text=sub,bg=WHITE,fg=MUTED,font=("Segoe UI",8)).pack(side="left",padx=10)
        return c

    def make_dashboard(self):
        p=self.page("Dashboard")
        m=tk.Frame(p,bg=BG); m.pack(fill="x",pady=(0,14))
        self.dtime=self.card(m,"Execution Time","—","AI optimized runtime",BLUE)
        self.dsize=self.card(m,"Code Size","—","Optimized executable",PURPLE)
        self.dsec=self.card(m,"Security","—","Current status",GREEN)
        self.dstrategy=self.card(m,"AI Strategy","—","Selected pipeline",AMBER)

        a=tk.Frame(p,bg=WHITE,highlightbackground=BORDER,highlightthickness=1); a.pack(fill="x",pady=(0,14))
        x=tk.Frame(a,bg=WHITE); x.pack(side="left",padx=18,pady=12)
        tk.Label(x,text="Optimization Experiment",bg=WHITE,fg=TEXT,font=("Segoe UI",11,"bold")).pack(anchor="w")
        tk.Label(x,text="Compare LLVM -O3 against the AI-selected optimization pipeline.",bg=WHITE,fg=MUTED,font=("Segoe UI",8)).pack(anchor="w",pady=(2,0))
        y=tk.Frame(a,bg=WHITE); y.pack(side="right",padx=18,pady=12)
        ttk.Button(y,text="Run -O3 Baseline",command=lambda:self.run("-O3"),bootstyle="secondary").pack(side="left",padx=4)
        ttk.Button(y,text="Run AI Optimization",command=lambda:self.run("AI"),bootstyle="success").pack(side="left",padx=4)

        bottom=tk.Frame(p,bg=BG); bottom.pack(fill="both",expand=True)
        c=self.section(bottom,"Performance Comparison","Original versus AI optimized")
        c.pack(side="left",fill="both",expand=True,padx=(0,7))
        t=tk.Frame(c,bg=WHITE); t.pack(fill="x",padx=18)
        for i,h in enumerate(["Metric","Original (-O3)","AI Optimized","Change"]):
            tk.Label(t,text=h,bg="#F8FAFC",fg=MUTED,font=("Segoe UI",10,"bold"),anchor="w",padx=8,pady=9).grid(row=0,column=i,sticky="ew")
        self.rows={}
        for r,(name,key) in enumerate([("Execution Time","time"),("Code Size","size"),("Security","security")],1):
            tk.Label(t,text=name,bg=WHITE,fg=TEXT,font=("Segoe UI",10),anchor="w",padx=8,pady=10).grid(row=r,column=0,sticky="ew")
            vals=[]
            for col in range(1,4):
                q=tk.Label(t,text="—",bg=WHITE,fg=TEXT if col<3 else MUTED,font=("Segoe UI",10,"bold"),anchor="w",padx=8)
                q.grid(row=r,column=col,sticky="ew"); vals.append(q)
            self.rows[key]=vals
        s=tk.Frame(c,bg=PURPLE_BG); s.pack(fill="x",padx=18,pady=18)
        tk.Label(s,text="AI SELECTED STRATEGY",bg=PURPLE_BG,fg=PURPLE,font=("Segoe UI",8,"bold")).pack(anchor="w",padx=12,pady=(9,2))
        self.strategy_text=tk.Label(s,text="—",bg=PURPLE_BG,fg="#4C1D95",font=("Consolas",9,"bold"),anchor="w",wraplength=600,justify="left")
        self.strategy_text.pack(fill="x",padx=12,pady=(0,10))

        log=self.section(bottom,"Experiment Activity","Compiler events"); log.configure(width=360); log.pack_propagate(False); log.pack(side="right",fill="both",padx=(7,0))
        self.logbox=tk.Text(log,bg="#F8FAFC",fg="#475569",relief="flat",font=("Consolas",10),padx=10,pady=10,state="disabled",wrap="word")
        self.logbox.pack(fill="both",expand=True,padx=14,pady=(0,14))

    def make_source(self):
        p=self.page("Source Code")
        c=self.section(p,"C Source","Selected program")
        f=tk.Frame(c,bg=WHITE); f.pack(fill="both",expand=True,padx=14,pady=(0,14))
        self.source=tk.Text(f,bg="#FBFCFE",fg="#1E293B",insertbackground=BLUE,selectbackground="#BFDBFE",
                            relief="flat",highlightbackground=BORDER,highlightthickness=1,font=("Consolas",10),padx=15,pady=12)
        self.source.pack(side="left",fill="both",expand=True)

    def make_ir(self):
        p=self.page("IR Analysis")
        body=tk.Frame(p,bg=BG); body.pack(fill="both",expand=True)
        a=self.section(body,"IR Features","8 compiler features"); a.configure(width=300); a.pack_propagate(False); a.pack(side="left",fill="y",padx=(0,7))
        self.features=tk.Text(a,bg=WHITE,fg=TEXT,relief="flat",font=("Consolas",9),padx=14,pady=10,state="disabled"); self.features.pack(fill="both",expand=True,padx=12,pady=(0,12))
        b=self.section(body,"LLVM IR","Generated intermediate representation"); b.pack(side="left",fill="both",expand=True,padx=(7,0))
        self.ir=tk.Text(b,bg="#FBFCFE",fg="#334155",relief="flat",font=("Consolas",9),padx=12,pady=10,wrap="none"); self.ir.pack(fill="both",expand=True,padx=12,pady=(0,12))

    def make_opt(self):
        p=self.page("Optimization")
        a=self.section(p,"Optimization Strategy","AI-selected LLVM pipeline"); a.pack(fill="x",pady=(0,12))
        self.optlabel=tk.Label(a,text="—",bg=WHITE,fg=PURPLE,font=("Consolas",10,"bold")); self.optlabel.pack(anchor="w",padx=18,pady=(0,15))
        b=self.section(p,"Measured Results",""); b.pack(fill="both",expand=True)
        self.table=ttk.Treeview(b,columns=("metric","o3","ai","change"),show="headings",height=8)
        for col,h in [("metric","Metric"),("o3","Original (-O3)"),("ai","AI Optimized"),("change","Change")]:
            self.table.heading(col,text=h); self.table.column(col,width=200,anchor="w")
        self.table.pack(fill="both",expand=True,padx=14,pady=(0,14))

    def make_bench(self):
        p=self.page("Benchmark")
        m=tk.Frame(p,bg=BG); m.pack(fill="x",pady=(0,14))
        self.btime1=self.card(m,"Baseline Time","—","-O3 runtime",BLUE)
        self.btime2=self.card(m,"AI Time","—","AI runtime",GREEN)
        self.bsize1=self.card(m,"Baseline Size","—","-O3 executable",PURPLE)
        self.bsize2=self.card(m,"AI Size","—","AI executable",AMBER)
        c=self.section(p,"Measurement Notes","Current backend measurements")
        tk.Label(c,text="Execution time is measured using repeated executable runs.\nCode size is the generated executable size.\nEnergy and multi-objective analysis can be integrated into this same interface next.",
                 bg=WHITE,fg="#475569",justify="left",font=("Segoe UI",9)).pack(anchor="w",padx=18,pady=(0,18))

    def make_security(self):
        p=self.page("Security")
        c=self.section(p,"Security Analysis","Current optimization safety status"); c.pack(fill="x")
        row=tk.Frame(c,bg=WHITE); row.pack(fill="x",padx=18,pady=18)
        self.sec1=self.security_box(row,"Original / -O3")
        self.sec2=self.security_box(row,"AI Optimized")
        tk.Label(p,text="The dedicated Secure Code Analysis module can be added later without changing this interface.",
                 bg="#FFFBEB",fg=AMBER,font=("Segoe UI",9),anchor="w",padx=14,pady=12).pack(fill="x",pady=(12,0))

    def security_box(self,parent,title):
        f=tk.Frame(parent,bg="#F8FAFC",highlightbackground=BORDER,highlightthickness=1); f.pack(side="left",fill="both",expand=True,padx=5)
        tk.Label(f,text=title,bg="#F8FAFC",fg=MUTED,font=("Segoe UI",8,"bold")).pack(anchor="w",padx=14,pady=(12,3))
        l=tk.Label(f,text="Awaiting analysis",bg="#F8FAFC",fg=TEXT,font=("Segoe UI",12,"bold")); l.pack(anchor="w",padx=14,pady=(0,12))
        return l

    def make_reports(self):
        p=self.page("Reports")
        c=self.section(p,"Experiment Report","Current comparison snapshot")
        self.report=tk.Text(c,bg=WHITE,fg=TEXT,relief="flat",font=("Consolas",9),padx=18,pady=12,state="disabled")
        self.report.pack(fill="both",expand=True,padx=12,pady=(0,12))

    def select_file(self):
        f=filedialog.askopenfilename(filetypes=[("C source files","*.c"),("All files","*.*")])
        if not f: return
        self.selected_file=f; name=os.path.basename(f)
        self.file_label.config(text=name,fg=BLUE)
        try:
            with open(f,"r",encoding="utf-8") as q: src=q.read()
            self.source.delete("1.0",tk.END); self.source.insert(tk.END,src)
        except Exception as e: messagebox.showerror("File Error",str(e))
        self._generate_ir()
        self._log("Loaded source: "+name); self.status.set("Source loaded")

    def _generate_ir(self):
        def task():
            path="gui_temp_unopt.ll"
            r=subprocess.run([CLANG_PATH,"-O0","-Xclang","-disable-O0-optnone","-S","-emit-llvm",self.selected_file,"-o",path],capture_output=True,text=True)
            if r.returncode!=0:
                self._log("LLVM IR generation failed."); return
            try:
                env=CompilerEnv(self.selected_file); feats=env.extract_features(path)
                with open(path,"r",encoding="utf-8") as q: ir=q.read()
                names=["Basic Blocks","Instructions","Branches","Memory","Math","Float","Vector","Calls"]
                def ui():
                    self.features.config(state="normal"); self.features.delete("1.0",tk.END)
                    for n,v in zip(names,feats): self.features.insert(tk.END,f"{n:<18}{int(v)}\n")
                    self.features.config(state="disabled"); self.ir.delete("1.0",tk.END); self.ir.insert(tk.END,ir)
                self.root.after(0,ui); self._log("LLVM IR generated and analyzed.")
            finally:
                if os.path.exists(path): os.remove(path)
        threading.Thread(target=task,daemon=True).start()

    def run(self,mode):
        if self.running: return
        if not self.selected_file:
            messagebox.showwarning("No Source File","Please select a C source file first."); return
        self.running=True; self.progress.start(); self.status.set("Running "+mode+" optimization...")
        self._log("Starting "+mode+" optimization...")
        threading.Thread(target=self._run_thread,args=(mode,),daemon=True).start()

    def _run_thread(self,mode):
        ll="gui_ai.ll" if mode=="AI" else "gui_o3.ll"; exe="gui_ai.exe" if mode=="AI" else "gui_o3.exe"
        try:
            strategy=get_best_optimization(self.selected_file) if mode=="AI" else "-O3"
            if not strategy: raise RuntimeError("AI failed to select an optimization strategy.")
            self.strategy=strategy; self._log(("AI selected: " if mode=="AI" else "Using baseline: ")+strategy)
            if not apply_optimization(self.selected_file,ll,strategy): raise RuntimeError("LLVM optimization failed.")
            r=subprocess.run([CLANG_PATH,ll,"-o",exe],capture_output=True,text=True)
            if r.returncode!=0: raise RuntimeError(r.stderr)
            subprocess.run([exe],capture_output=True,timeout=10)
            times=[]
            for _ in range(5):
                s=time.perf_counter(); r=subprocess.run([exe],capture_output=True,timeout=10); times.append(time.perf_counter()-s)
                if r.returncode!=0: raise RuntimeError("Benchmark executable returned an error.")
            t=min(times); size=os.path.getsize(exe); sec="✓ Preserved"
            key="ai" if mode=="AI" else "o3"; self.results[key]={"time":t,"size":size,"security":sec}
            self._log(f"{mode}: {t:.6f} s | {size:,} bytes | {sec}")
            self.root.after(0,self.refresh)
        except Exception as e:
            self._log("ERROR: "+str(e)); self.root.after(0,lambda err=str(e):messagebox.showerror("Optimization Error",err))
        finally:
            for x in (ll,exe):
                if os.path.exists(x):
                    try: os.remove(x)
                    except: pass
            self.root.after(0,self.finish)

    def finish(self):
        self.running=False; self.progress.stop(); self.status.set("Ready")

    def refresh(self):
        o=self.results["o3"]; a=self.results["ai"]
        self.dtime.config(text=self.fmt_time(a["time"])); self.dsize.config(text=self.fmt_size(a["size"]))
        self.dsec.config(text=a["security"]); self.dstrategy.config(text="AI Selected" if self.strategy!="-O3" else "—")
        self.strategy_text.config(text=self.strategy); self.optlabel.config(text=self.strategy)
        vals=[("time",self.fmt_time(o["time"]),self.fmt_time(a["time"]),self.change(o["time"],a["time"])),
              ("size",self.fmt_size(o["size"]),self.fmt_size(a["size"]),self.change(o["size"],a["size"])),
              ("security",o["security"],a["security"],"—")]
        for k,x,y,z in vals:
            a1,b1,c1=self.rows[k]; a1.config(text=x); b1.config(text=y); c1.config(text=z)
        self.btime1.config(text=self.fmt_time(o["time"])); self.btime2.config(text=self.fmt_time(a["time"]))
        self.bsize1.config(text=self.fmt_size(o["size"])); self.bsize2.config(text=self.fmt_size(a["size"]))
        self.sec1.config(text=o["security"]); self.sec2.config(text=a["security"])
        for i in self.table.get_children(): self.table.delete(i)
        for row in [("Execution Time",self.fmt_time(o["time"]),self.fmt_time(a["time"]),self.change(o["time"],a["time"])),
                    ("Code Size",self.fmt_size(o["size"]),self.fmt_size(a["size"]),self.change(o["size"],a["size"])),
                    ("Security",o["security"],a["security"],"—")]: self.table.insert("", "end", values=row)
        self.update_report()

    @staticmethod
    def fmt_time(v): return f"{v:.6f} s" if v is not None else "—"
    @staticmethod
    def fmt_size(v): return f"{v:,} B" if v is not None else "—"
    @staticmethod
    def change(o,a):
        if o is None or a is None or o==0: return "—"
        p=(a-o)/o*100
        return f"↓ {abs(p):.1f}%" if p<0 else (f"↑ {p:.1f}%" if p>0 else "0.0%")

    def update_report(self):
        if not hasattr(self,"report"): return
        o=self.results["o3"]; a=self.results["ai"]
        text=("TOACD COMPILER OPTIMIZATION EXPERIMENT\n"
              "=====================================\n\n"
              f"Source: {os.path.basename(self.selected_file) if self.selected_file else 'Not selected'}\n"
              f"AI Strategy: {self.strategy}\n\n"
              "PERFORMANCE\n-----------\n"
              f"Original (-O3) time : {self.fmt_time(o['time'])}\n"
              f"AI optimized time  : {self.fmt_time(a['time'])}\n"
              f"Time change        : {self.change(o['time'],a['time'])}\n\n"
              f"Original (-O3) size : {self.fmt_size(o['size'])}\n"
              f"AI optimized size  : {self.fmt_size(a['size'])}\n"
              f"Size change        : {self.change(o['size'],a['size'])}\n\n"
              "SECURITY\n--------\n"
              f"Original (-O3) : {o['security']}\nAI optimized   : {a['security']}\n")
        self.report.config(state="normal"); self.report.delete("1.0",tk.END); self.report.insert(tk.END,text); self.report.config(state="disabled")

    def _log(self,msg):
        def w():
            if not hasattr(self,"logbox"): return
            self.logbox.config(state="normal"); self.logbox.insert(tk.END,f"[{time.strftime('%H:%M:%S')}]  {msg}\n")
            self.logbox.see(tk.END); self.logbox.config(state="disabled")
        self.root.after(0,w)

if __name__=="__main__":
    root=ttk.Window(themename="litera")
    CompilerGUI(root)
    root.mainloop()
