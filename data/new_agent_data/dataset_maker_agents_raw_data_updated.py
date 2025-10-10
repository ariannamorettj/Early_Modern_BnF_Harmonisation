import os
import csv
import time
import random
import threading
from pathlib import Path
from SPARQLWrapper import SPARQLWrapper, JSON
from tqdm import tqdm
import pandas as pd
from datetime import datetime
import shutil
import psutil
import gpustat
import speedtest
import sys


sparql = SPARQLWrapper("https://data.bnf.fr/sparql")
sparql.setReturnFormat(JSON)

OUTPUT_DIR = Path("results_agents")
START_YEAR = 1454
END_YEAR = 1799
BATCH_SIZE = 2000
ROLES = {
    "aut": "author",
    "trl": "translator",
    "edt": "editor",
    "ill": "illustrator",
    "pbl": "publisher"
}

PREFIXES = """
PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
PREFIX bnf-onto: <http://data.bnf.fr/ontology/bnf-onto/>
PREFIX rdarelationships: <http://rdvocab.info/RDARelationshipsWEMI/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdam: <http://rdaregistry.info/Elements/m/#> 
PREFIX marcrel: <http://id.loc.gov/vocabulary/relators/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/> 
PREFIX bio: <http://vocab.org/bio/0.1/> 
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Bring the monitor code functions here because the machine spirits of Windows
# do not like importing them from the script

RESUME_INFO_FILE = "resume_info.log"  # Name of the log file preserving resume history


def get_system_usage():
    """
    Collect aggregate system metrics:
      • CPU usage percentage
      • Memory usage percentage
      • Disk usage percentage
      • Total network bytes sent and received
    Returns:
        cpu_percent (float), memory_percent (float), disk_percent (float),
        bytes_sent (int), bytes_recv (int)
    """
    cpu_percent = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    memory_percent = mem.percent
    disk = psutil.disk_usage('/')
    disk_percent = disk.percent
    net = psutil.net_io_counters()
    return cpu_percent, memory_percent, disk_percent, net.bytes_sent, net.bytes_recv


def get_gpu_usage():
    """
    Query GPU statistics via gpustat.
    On failure (e.g. no GPU present), returns zeros.
    Returns:
        gpu_util (int), gpu_mem_used (int)
    """
    try:
        stats = gpustat.GPUStatCollection.new_query()
        gpu = stats[0]
        return gpu.utilization, gpu.memory_used
    except Exception:
        return 0, 0


def get_connection_speed():
    """
    Measure network throughput using speedtest, but if the library isn’t
    available or any error occurs, gracefully fall back to zeros.

    Returns:
        tuple:
          – download_speed (float): Mbps, or 0.0 on failure
          – upload_speed   (float): Mbps, or 0.0 on failure
    """
    try:
        # look up the Speedtest class dynamically
        Speedtest = getattr(speedtest, 'Speedtest', None)
        if Speedtest is None:
            return 0.0, 0.0

        st = Speedtest()
        st.get_best_server()
        # convert from bits/s to Mbits/s
        download = st.download() / 1e6
        upload   = st.upload()   / 1e6
        return download, upload

    except Exception:
        # any issue (missing attribute, network error, etc.) becomes a zero reading
        return 0.0, 0.0

def monitor_process():
    """
    Obtain a handle to the current process for per-process metrics.
    Returns:
        psutil.Process instance for the running Python process.
    """
    return psutil.Process(os.getpid())


def monitor_system():
    """
    Persistent system and process monitoring routine:
      • Prints existing resume info from RESUME_INFO_FILE if present.
      • Sets up a tqdm progress bar to indicate ongoing monitoring cycles.
      • Enters an infinite loop, reporting:
          – System CPU, memory, disk usage
          – GPU utilization and memory
          – Network download/upload speeds
          – Current process CPU and memory usage
      • Sleeps between iterations to throttle reporting frequency.
    """
    if os.path.exists(RESUME_INFO_FILE):
        with open(RESUME_INFO_FILE, "r") as f:
            resume_info = f.read().strip()
        print(f"\n[RESUME INFO] {resume_info}\n")

    print("Monitoring loop initiated: reporting system and process metrics")
    pbar = tqdm(total=100, desc="Monitoring", ncols=100, unit="s")  # progress bar

    proc = monitor_process()

    while True:
        # Gather system-wide statistics
        cpu, mem, disk, sent, recv = get_system_usage()
        gpu_util, gpu_mem = get_gpu_usage()
        dl, ul = get_connection_speed()

        # Gather per-process statistics
        cpu_proc = proc.cpu_percent(interval=1)
        mem_info = proc.memory_info()
        mem_proc_pct = mem_info.rss / psutil.virtual_memory().total * 100

        # Structured reporting
        print(f"System — CPU: {cpu}% | Mem: {mem}% | Disk: {disk}%")
        print(f"GPU    — Util: {gpu_util}% | MemUsed: {gpu_mem} MB")
        print(f"Network— Dl: {dl:.2f} Mbps | Ul: {ul:.2f} Mbps")
        print(f"Process— CPU: {cpu_proc}% | Mem: {mem_proc_pct:.2f}%")

        pbar.update(1)
        time.sleep(5)



def format_seconds(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02}:{m:02}:{s:02}"

def now_str():
    return datetime.now().strftime("%A, %Y-%m-%d %H:%M:%S")

def get_monitor_log():
    proc = monitor_process()
    cpu, mem, disk, sent, recv = get_system_usage()
    gpu_util, gpu_mem = get_gpu_usage()
    dl, ul = get_connection_speed()
    cpu_proc = proc.cpu_percent(interval=1)
    try:
        import psutil
        mem_proc_pct = proc.memory_info().rss / psutil.virtual_memory().total * 100
    except Exception:
        mem_proc_pct = 0

    return (
        f"System — CPU: {cpu}% | Mem: {mem}% | Disk: {disk}%\n"
        f"GPU    — Util: {gpu_util}% | MemUsed: {gpu_mem} MB\n"
        f"Network— Dl: {dl:.2f} Mbps | Ul: {ul:.2f} Mbps\n"
        f"Process— CPU: {cpu_proc}% | Mem: {mem_proc_pct:.2f}%\n"
    )

def write_monitor_log(log_path):
    log = get_monitor_log()
    with open(log_path, "a") as f:
        f.write(log + "\n")
    print(log.strip())

def build_query(year, offset, role):
    return f"""
    {PREFIXES}
    SELECT DISTINCT ?actor ?entity_type ?actor_name ?actor_first_name ?actor_last_name ?actor_country ?actor_language ?actor_gender 
                    ?actor_profession ?actor_birth ?actor_death 
                    ?actor_start ?actor_end ?actor_link_exact ?actor_link_close
    WHERE {{
        ?edition bnf-onto:firstYear ?year_first.
        ?edition rdarelationships:expressionManifested ?expression.
        ?expression marcrel:{role} ?actor.
        OPTIONAL {{ ?actor rdf:type ?entity_type.}}
        OPTIONAL {{ ?actor foaf:name ?actor_name. }}
        OPTIONAL {{ ?actor foaf:givenName ?actor_first_name. }}
        OPTIONAL {{ ?actor foaf:familyName ?actor_last_name. }}
        OPTIONAL {{ ?actor rdagroup2elements:countryAssociatedWithThePerson ?actor_country. }}
        OPTIONAL {{ ?actor rdagroup2elements:languageOfThePerson ?actor_language. }}
        OPTIONAL {{ ?actor foaf:gender ?actor_gender. }}
        OPTIONAL {{ ?actor rdagroup2elements:biographicalInformation ?actor_profession. }}
        OPTIONAL {{ ?actor bio:birth ?actor_birth. }}
        OPTIONAL {{ ?actor bio:death ?actor_death. }}
        OPTIONAL {{ ?actor bnf-onto:firstYear ?actor_start. }}
        OPTIONAL {{ ?actor bnf-onto:lastYear ?actor_end. }}
        OPTIONAL {{ ?person foaf:focus ?actor. ?person skos:exactMatch ?actor_link_exact. }}
        OPTIONAL {{ ?person foaf:focus ?actor. ?person skos:closeMatch ?actor_link_close. }}
        FILTER(?year_first = {year})
    }}
    OFFSET {offset}
    LIMIT {BATCH_SIZE}
    """

def execute_query(year, offset, role):
    sparql.setQuery(build_query(year, offset, role))
    return sparql.query().convert()["results"]["bindings"]

def get_shortlist_path(role):
    return OUTPUT_DIR / f"shortlist_{role}.csv"

def update_shortlist(role, new_actors):
    path = get_shortlist_path(role)
    if path.exists():
        existing = pd.read_csv(path)
        combined = pd.concat([existing, new_actors]).drop_duplicates(subset=["actor"])
    else:
        combined = new_actors
    combined.to_csv(path, index=False)

def process_year_and_role(year, role, global_report, year_report):
    role_dir = OUTPUT_DIR / str(year) / role
    os.makedirs(role_dir, exist_ok=True)
    report_path = role_dir / "_report.txt"
    csv_path = role_dir / f"_{role}.csv"
    monitor_path = role_dir / "_monitor.txt"
    start_time = time.time()

    system_log = get_monitor_log()
    start_line = f"Start processing {role_dir} at {now_str()}, Elapsed time: {format_seconds(start_time - START_GLOBAL)}\n"

    global_report.write(start_line + system_log + "\n")
    year_report.write(start_line + system_log + "\n")

    headers = []
    rows = []
    offset = 0
    total_records = 0

    with open(report_path, "w") as report_file:
        report_file.write(f"Start year {year}, role {role}: {now_str()}\n")

    while True:
        try:
            bindings = execute_query(year, offset, role)
            if not bindings:
                break

            if not headers and bindings:
                headers = list(bindings[0].keys())

            for result in bindings:
                row = [result.get(h, {}).get("value", "") for h in headers]
                rows.append(row)

            offset += BATCH_SIZE
            total_records += len(bindings)

            write_monitor_log(monitor_path)
            write_monitor_log(OUTPUT_DIR / "_global_monitor.txt")

            time.sleep(5 + random.random() * 5)

        except Exception as e:
            with open(report_path, "a") as report_file:
                report_file.write(f"Error at offset {offset}: {e}\n")
            break

    if rows:
        df = pd.DataFrame(rows, columns=headers)
        df.to_csv(csv_path, index=False)
        update_shortlist(role, df[["actor"]].drop_duplicates())

    elapsed = time.time() - start_time
    end_line = f"Finish processing {role_dir} at {now_str()}, Elapsed time for subprocess: {format_seconds(elapsed)}\n"
    system_log = get_monitor_log()

    with open(report_path, "a") as report_file:
        report_file.write(f"\n√ Finished {year}-{role} in {format_seconds(elapsed)}, total rows: {total_records}\n")

    global_report.write(end_line + system_log + "\n")
    year_report.write(end_line + system_log + "\n")

    print(f"√ Year {year} Role {role} completed in {format_seconds(elapsed)} with {total_records} rows")

def detect_last_completed_year():
    if not OUTPUT_DIR.exists():
        return START_YEAR
    year_dirs = [int(d.name) for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name.isdigit()]
    if not year_dirs:
        return START_YEAR
    last = max(year_dirs)
    shutil.rmtree(OUTPUT_DIR / str(last))
    return last

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    start_year = detect_last_completed_year()

    global_report_path = OUTPUT_DIR / "_report_global.txt"
    global_report = open(global_report_path, "w")
    global_report.write(f"Process started at: {now_str()}\n")
    global_report.write("Queries skipped: []\n")

    for year in tqdm(range(start_year, END_YEAR + 1), desc="Processing years"):
        year_dir = OUTPUT_DIR / str(year)
        os.makedirs(year_dir, exist_ok=True)
        year_report_path = year_dir / "_report_per_year.txt"
        year_report = open(year_report_path, "w")

        header = f"Start processing {year} at {now_str()}, Elapsed time: {format_seconds(time.time() - START_GLOBAL)}\n"
        global_report.write(header)
        year_report.write(header)

        for role in ROLES:
            process_year_and_role(year, role, global_report, year_report)

        year_report.close()

    global_report.close()

if __name__ == "__main__":
    START_GLOBAL = time.time()
    monitor_thread = threading.Thread(target=monitor_system, daemon=True)
    monitor_thread.start()
    main()
