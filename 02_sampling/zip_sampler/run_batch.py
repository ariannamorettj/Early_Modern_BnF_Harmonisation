import sys
import os
from zip_sampler import generate_report

def run_batch(output_dir, zip_files):
    os.makedirs(output_dir, exist_ok=True)
    for z in zip_files:
        if os.path.exists(z):
            print(f"Processing {z}...")
            report = generate_report(z, output_dir)
            print(f"Report saved: {report}")
        else:
            print(f"{z} not found, skipping.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python run_batch.py <output_dir> <zip1> [<zip2> ...]")
        sys.exit(1)
    output = sys.argv[1]
    zips = sys.argv[2:]
    run_batch(output, zips)


### SAMPLE RUN
'''
python zip_sampler/run_batch.py zip_sampler/reports \
    data/new_agent_data/results_agents_new.zip \
    data/bnf_agents_data_gap_filling/actor_queries_results_for_actors_missing_from_bnf_editions.zip \
    data/bnf_agents_data_gap_filling/missing_agent_data_supplement.zip
'''

'''
python zip_sampler/run_batch.py zip_sampler/reports \
    data/bnf_agents_data_querying/actor_queries_results.zip
'''