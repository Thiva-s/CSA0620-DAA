# GREEN-SCHED — Local DAA Project

A browser dashboard for **Green Task Scheduling for Energy-Efficient Cloud Computing**.

## Requirements
- Python 3.9 or newer
- Chrome, Firefox, or Edge
- No Python packages are required (Python standard library only).

## Run on Windows
1. Extract this ZIP.
2. Open the `GREEN-SCHED-Local` folder.
3. Double-click `run_windows.bat`.
4. The dashboard opens at http://127.0.0.1:8000.

## Run on Linux / Kali Linux / macOS
Open a terminal in this folder and run:
```bash
python3 main.py
```
Then open http://127.0.0.1:8000 in your browser. Stop the server with Ctrl+C.

## Included algorithms
1. Merge Sort — priority/deadline ordering.
2. Topological Sort — dependency-safe execution order.
3. Binary Search — smallest suitable server capacity.
4. Greedy scheduling — assign tasks to energy-efficient servers.
5. 0/1 Knapsack Dynamic Programming — select workloads under an energy budget.
6. Backtracking — explore assignments for up to 12 tasks.
7. Dijkstra — minimum-cost communication route.

## Dashboard features
- Change task count, server count, energy budget, carbon intensity and workload seed.
- Generate a repeatable workload with dependencies.
- Run Greedy, Knapsack DP and Backtracking on the same workload.
- View assignments, server utilization, completion, deadline misses, energy and estimated carbon.
- Export benchmark results to CSV.

## Research / simulation note
This is a local educational simulator. Energy and carbon figures are model estimates based on illustrative server power values, not measurements from AWS, Azure or another cloud provider. Backtracking is limited to 12 tasks because its worst-case search is exponential. Knapsack DP uses a discretized energy budget.

## Troubleshooting
- If port 8000 is busy, edit `PORT = 8000` near the top of `main.py` to another free port (for example 8080).
- If the browser does not open automatically, manually visit http://127.0.0.1:8000.
- Keep the terminal window open while using the dashboard.
