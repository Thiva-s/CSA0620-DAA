from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
import json, random, time, threading, webbrowser
from pathlib import Path
import sys
from copy import deepcopy

ROOT = Path(__file__).parent
# Reuse the project's real Heap Sort -> FFD -> Greedy VM scheduler.
PROJECT_ROOT = ROOT.parent / "GreenCloudScheduler"
sys.path.insert(0, str(PROJECT_ROOT))
from simulation.vm_simulator import run_scheduling_pipeline
from simulation.energy_calculator import compute_baseline_energy, energy_savings_percent

HOST, PORT = "127.0.0.1", 8000

def merge_sort(items, key):
    if len(items) <= 1: return items[:]
    mid = len(items)//2
    left, right = merge_sort(items[:mid], key), merge_sort(items[mid:], key)
    out=[]; i=j=0
    while i < len(left) and j < len(right):
        if key(left[i]) <= key(right[j]): out.append(left[i]); i+=1
        else: out.append(right[j]); j+=1
    return out + left[i:] + right[j:]

def topological_sort(tasks):
    by_id={t["id"]:t for t in tasks}
    indeg={t["id"]:0 for t in tasks}
    graph={t["id"]:[] for t in tasks}
    for t in tasks:
        for dep in t["dependencies"]:
            if dep in by_id:
                graph[dep].append(t["id"]); indeg[t["id"]]+=1
    ready=sorted([k for k,v in indeg.items() if v==0])
    order=[]
    while ready:
        u=ready.pop(0); order.append(u)
        for v in graph[u]:
            indeg[v]-=1
            if indeg[v]==0:
                ready.append(v); ready.sort()
    if len(order)!=len(tasks): raise ValueError("Dependency cycle detected. Generate a fresh workload.")
    return order

def binary_search_capacity(capacities, required):
    lo, hi=0,len(capacities)-1; ans=-1
    while lo<=hi:
        mid=(lo+hi)//2
        if capacities[mid]>=required: ans=mid; hi=mid-1
        else: lo=mid+1
    return ans

def dijkstra(graph, start, end):
    import heapq
    dist={n:float("inf") for n in graph}; prev={}
    dist[start]=0; heap=[(0,start)]
    while heap:
        d,u=heapq.heappop(heap)
        if d!=dist[u]: continue
        if u==end: break
        for v,w in graph[u]:
            nd=d+w
            if nd<dist[v]: dist[v]=nd; prev[v]=u; heapq.heappush(heap,(nd,v))
    if dist[end]==float("inf"): return [], None
    path=[]; cur=end
    while cur!=start: path.append(cur); cur=prev[cur]
    path.append(start); return path[::-1],dist[end]

def make_workload(n, server_count, seed=42):
    rng=random.Random(seed)
    tasks=[]
    for i in range(n):
        # dependencies always point to earlier task IDs, so the generated graph is acyclic
        deps=[]
        if i>1 and rng.random()<0.24:
            deps=[f"T{x:02d}" for x in sorted(rng.sample(range(max(1,i-4),i), k=1))]
        tasks.append({
            "id":f"T{i+1:02d}",
            "name":["API aggregation","Data cleaning","Model inference","Report build","Cache refresh","ETL transform","Image processing","Log analysis"][i%8],
            "cpu":rng.randint(1, min(8, max(2,server_count*2))),
            "duration":rng.randint(3,18),
            "priority":rng.randint(1,5),
            "deadline":rng.randint(18, max(24,n*5)),
            "energy":round(rng.uniform(0.5,3.2),2),
            "dependencies":deps
        })
    return tasks

def make_servers(m):
    return [{"id":f"S{i+1}","name":f"Node {i+1}","capacity":cap,"power":power}
            for i,(cap,power) in enumerate([(2,0.42),(4,0.68),(6,0.91),(8,1.18),(12,1.55)][:m])]

def schedule_greedy(tasks, servers):
    # Kahn topological order keeps prerequisites ahead of dependent tasks.
    by_id={t["id"]:t for t in tasks}
    order=topological_sort(tasks)
    capacities=sorted(s["capacity"] for s in servers)
    assignments=[]; used={s["id"]:0 for s in servers}; energy=0; finish=0; misses=0
    completion={}
    for tid in order:
        t=by_id[tid]
        idx=binary_search_capacity(capacities,t["cpu"])
        candidates=[s for s in servers if s["capacity"]>=t["cpu"]]
        if not candidates:
            assignments.append({"task":t["id"],"server":"Unassigned","status":"Capacity exceeded","energy":0,"finish":None})
            completion[tid]=0
            continue
        # Choose the smallest eligible low-power node; respect dependency finish times.
        s=min(candidates,key=lambda x:(x["capacity"],x["power"]))
        dependency_ready=max([completion.get(dep,0) for dep in t["dependencies"]],default=0)
        start=max(used[s["id"]],dependency_ready)
        duration=t["duration"]*(t["cpu"]/s["capacity"])
        end=start+duration; used[s["id"]]=end; completion[tid]=end
        e=round(s["power"]*duration/60,3); energy+=e; finish=max(finish,end)
        late=end>t["deadline"]; misses+=int(late)
        assignments.append({"task":t["id"],"server":s["id"],"status":"Late" if late else "Scheduled","energy":e,"finish":round(end,1)})
    return assignments, round(energy,3), misses, round(finish,1), used

def schedule_knapsack(tasks, servers, budget):
    # 0/1 knapsack selects the maximum priority-weighted workload under an energy budget.
    scale=10; cap=max(0,int(budget*scale))
    dp=[(0,[]) for _ in range(cap+1)]
    for i,t in enumerate(tasks):
        weight=max(1,int(t["energy"]*scale))
        value=t["priority"]*100 + max(0,30-t["duration"])
        for b in range(cap,weight-1,-1):
            cand=(dp[b-weight][0]+value,dp[b-weight][1]+[i])
            if cand[0]>dp[b][0]: dp[b]=cand
    chosen=set(dp[cap][1])
    # A task is not selectable unless all of its prerequisites are selected.
    changed=True
    while changed:
        changed=False
        for i in list(chosen):
            deps=tasks[i]["dependencies"]
            missing=[dep for dep in deps if not any(tasks[j]["id"]==dep for j in chosen)]
            if missing:
                chosen.remove(i); changed=True
    selected=[t for i,t in enumerate(tasks) if i in chosen]
    assignments, energy, misses, finish, used=schedule_greedy(selected,servers)
    skipped=[{"task":t["id"],"server":"Not selected","status":"Energy budget","energy":0,"finish":None} for i,t in enumerate(tasks) if i not in chosen]
    return assignments+skipped,energy,misses,finish,used,len(selected)

def schedule_backtracking(tasks, servers, budget, max_tasks=12):
    if len(tasks)>max_tasks:
        raise ValueError(f"Backtracking is limited to {max_tasks} tasks to keep the search responsive. Reduce task count.")
    # Explore all feasible server placements; objective is minimum energy with deadline penalties.
    best=None; states=0; used={s["id"]:0.0 for s in servers}; chosen=[]
    ordered=topological_sort(tasks)
    by_id={t["id"]:t for t in tasks}
    completion={}
    def dfs(pos, energy, penalty):
        nonlocal best,states
        states+=1
        if best and energy+penalty>=best[0]: return
        if pos==len(ordered):
            best=(energy+penalty,chosen.copy(),energy,penalty); return
        tid=ordered[pos]; t=by_id[tid]
        eligible=sorted([s for s in servers if s["capacity"]>=t["cpu"]],key=lambda s:s["power"])
        dependency_ready=max([completion.get(dep,0) for dep in t["dependencies"]],default=0)
        for s in eligible:
            start=max(used[s["id"]],dependency_ready); dur=t["duration"]*(t["cpu"]/s["capacity"]); end=start+dur
            e=s["power"]*dur/60
            if energy+e>budget: continue
            old_completion=completion.get(tid)
            used[s["id"]]=end; completion[tid]=end; chosen.append((tid,s["id"],end,e))
            dfs(pos+1,energy+e, max(0,end-t["deadline"])*0.04)
            chosen.pop(); used[s["id"]]=start
            if old_completion is None: completion.pop(tid,None)
            else: completion[tid]=old_completion
        # A skip branch makes infeasible workloads still produce a valid solution.
        old_completion=completion.get(tid)
        completion[tid]=completion.get(tid,0)
        chosen.append((tid,"Unassigned",None,0)); dfs(pos+1,energy,penalty+100); chosen.pop()
        if old_completion is None: completion.pop(tid,None)
        else: completion[tid]=old_completion
    dfs(0,0,0)
    rows=best[1] if best else []
    assignments=[{"task":tid,"server":sid,"status":"Scheduled" if sid!="Unassigned" else "Unassigned",
                  "energy":round(e,3),"finish":round(end,1) if end is not None else None} for tid,sid,end,e in rows]
    total=round(sum(x["energy"] for x in assignments),3)
    misses=sum(1 for x in assignments if x["status"]=="Unassigned")
    finish=max([x["finish"] or 0 for x in assignments],default=0)
    return assignments,total,misses,round(finish,1),used,states

def network_route(servers):
    graph={s["id"]:[] for s in servers}
    for i,s in enumerate(servers):
        if i+1<len(servers):
            w=round(abs(s["power"]-servers[i+1]["power"])*10+1,2)
            graph[s["id"]].append((servers[i+1]["id"],w))
            graph[servers[i+1]["id"]].append((s["id"],w))
        if i+2<len(servers):
            w=round(abs(s["power"]-servers[i+2]["power"])*10+3,2)
            graph[s["id"]].append((servers[i+2]["id"],w))
            graph[servers[i+2]["id"]].append((s["id"],w))
    return dijkstra(graph,servers[0]["id"],servers[-1]["id"])

def run_simulation(payload):
    n=max(3,min(40,int(payload.get("taskCount",12))))
    m=max(2,min(5,int(payload.get("serverCount",4))))
    budget=max(1,min(100,float(payload.get("energyBudget",12))))
    carbon=max(0,min(1000,float(payload.get("carbonIntensity",420))))
    seed=int(payload.get("seed",42))
    rng=random.Random(seed)
    max_cpu=min(4, max(2,m))
    max_ram=max(1, (sum(v[1] for v in [(2,4),(4,8),(6,16),(8,24),(12,32)][:m]) // max(n,1)))
    tasks=[]
    for i in range(n):
        tasks.append({"id":i+1,"name":f"{['API aggregation','Data cleaning','Model inference','Report build','Cache refresh','ETL transform','Image processing','Log analysis'][i%8]}-{i+1:02d}",
                      "cpu_req":rng.randint(1, max_cpu), "ram_req":rng.randint(1,max_ram),
                      "exec_time":round(rng.uniform(0.25,3.5),2),"priority":rng.randint(1,5),
                      "status":"pending","assigned_vm_id":None})
    profiles=[(2,4,28,90),(4,8,40,150),(6,16,58,210),(8,24,75,280),(12,32,100,360)]
    vms=[{"id":i+1,"name":f"Node {i+1}","cpu_cores":profiles[i][0],"ram_total":profiles[i][1],
          "idle_power":profiles[i][2],"max_power":profiles[i][3],"cpu_used":0,"ram_used":0,"status":"sleeping"}
         for i in range(m)]
    baseline_tasks=deepcopy(tasks)
    scheduled=run_scheduling_pipeline(tasks,vms,time_hours=max(0.25,min(8,budget/4)))
    # Convert pipeline allocations to the existing UI's server/task vocabulary.
    assignments=[]
    alloc_by_task={a["task"]["id"]:a["vm"] for a in scheduled["allocations"]}
    unscheduled_ids={t["id"] for t in scheduled["unscheduled"]}
    energy_by_vm={}
    for vm in scheduled["vms"]:
        if vm["status"]!="sleeping":
            from simulation.energy_calculator import compute_vm_energy
            _, energy_by_vm[vm["id"]]=compute_vm_energy(vm,max(0.25,min(8,budget/4)))
    for task in tasks:
        vm=alloc_by_task.get(task["id"])
        assignments.append({"task":task["name"],"server":vm["id"] if vm else "Unassigned",
                            "status":"Scheduled" if vm else "Capacity exceeded","energy":round(energy_by_vm.get(vm["id"],0),3) if vm else 0,
                            "finish":round(task["exec_time"]*60,1) if vm else None})
    total=scheduled["total_energy_wh"]
    baseline=compute_baseline_energy(baseline_tasks,scheduled["vms"],max(0.25,min(8,budget/4)))
    savings=energy_savings_percent(baseline,total)
    completed=len(scheduled["allocations"])
    utilization=round(sum(v["cpu_used"] for v in scheduled["vms"])/max(1,sum(v["cpu_cores"] for v in scheduled["vms"]))*100,1)
    result={"name":"GreenCloudScheduler pipeline","energy":round(total,3),"carbon":round(total*carbon/1000,4),
            "completed":completed,"total":n,"completionRate":round(completed/n*100,1),
            "deadlineMisses":len(unscheduled_ids),"makespan":None,"utilization":utilization,"assignments":assignments,
            "baselineEnergy":round(baseline,3),"savingsPercent":round(savings,2),
            "explanations":scheduled["explanations"]}
    server_rows=[{"id":v["id"],"name":v["name"],"capacity":v["cpu_cores"],"ram":v["ram_total"],
                  "power":v["max_power"],"status":v["status"],"usedCpu":v["cpu_used"],"usedRam":v["ram_used"]} for v in scheduled["vms"]]
    task_rows=[{"id":f"T{t['id']:02d}","name":t["name"],"cpu":t["cpu_req"],"ram":t["ram_req"],
                "duration":round(t["exec_time"]*60),"priority":t["priority"],"deadline":"—","energy":0,"dependencies":[]} for t in tasks]
    return {"tasks":task_rows,"servers":server_rows,"sortedTaskIds":[f"T{t['id']:02d}" for t in tasks],
            "topologicalOrder":[f"T{t['id']:02d}" for t in tasks],"network":{"path":[],"cost":None},"results":[result],
            "algorithmNotes":[
                {"name":"Heap Sort","complexity":"O(n log n)","purpose":"Order pending tasks by descending priority."},
                {"name":"First Fit Decreasing","complexity":"O(n log n + nm)","purpose":"Process high resource demand tasks first and consolidate onto active VMs."},
                {"name":"Greedy VM Selection","complexity":"O(nm)","purpose":"Prefer a running VM that fits; otherwise choose the feasible VM with the lowest incremental power cost."},
                {"name":"VM Consolidation","complexity":"O(m)","purpose":"Put unused virtual machines to sleep after allocation."}
            ],
            "settings":{"taskCount":n,"serverCount":m,"energyBudget":budget,"carbonIntensity":carbon,"seed":seed},
            "disclaimer":"Simulation estimates only. Energy and carbon values are modelled from illustrative server power values, not measured cloud-provider telemetry."}

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, data, content_type="application/json; charset=utf-8"):
        raw=data if isinstance(data,bytes) else data.encode()
        self.send_response(code); self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store")
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path=urlparse(self.path).path
        if path in ("/","/index.html"):
            self._send(200,(ROOT/"static"/"index.html").read_bytes(),"text/html; charset=utf-8")
        elif path=="/style.css":
            self._send(200,(ROOT/"static"/"style.css").read_bytes(),"text/css; charset=utf-8")
        elif path=="/app.js":
            self._send(200,(ROOT/"static"/"app.js").read_bytes(),"application/javascript; charset=utf-8")
        elif path=="/api/health": self._send(200,json.dumps({"status":"ok","app":"GREEN-SCHED"}))
        else: self._send(404,json.dumps({"error":"Not found"}))
    def do_POST(self):
        if urlparse(self.path).path!="/api/run": self._send(404,json.dumps({"error":"Not found"})); return
        try:
            length=int(self.headers.get("Content-Length","0"))
            payload=json.loads(self.rfile.read(length) or b"{}")
            self._send(200,json.dumps(run_simulation(payload)))
        except Exception as e: self._send(400,json.dumps({"error":str(e)}))
    def log_message(self,*args): pass

if __name__=="__main__":
    try:
        server=HTTPServer((HOST,PORT),Handler)
    except OSError as e:
        print(f"Could not start GREEN-SCHED on http://{HOST}:{PORT}: {e}")
        print("Stop the other process using port 8000, or change PORT near the top of main.py.")
        raise SystemExit(1)
    print("\\n GREEN-SCHED local dashboard")
    print(f" Open http://{HOST}:{PORT} in your browser")
    print(" Press Ctrl+C to stop the server\\n")
    try:
        threading.Timer(1.0,lambda:webbrowser.open(f"http://{HOST}:{PORT}")).start()
        server.serve_forever()
    except KeyboardInterrupt: print("\\nServer stopped.")
    finally: server.server_close()
