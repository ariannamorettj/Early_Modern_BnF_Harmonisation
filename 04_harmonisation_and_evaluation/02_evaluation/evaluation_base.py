import csv
import os
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable, Any
from tqdm import tqdm


@dataclass
class CaseConfig:
    label: str
    pattern: Optional[str] = None


class Evaluation:
    """
    Classe base per la valutazione di un singolo campo di uno o più CSV.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        csv_filepath: str,
        field_name: Optional[str] = None,
    ) -> None:
        """
        Parameters
        ----------
        config : dict
            Configurazione del campo da valutare (derivata da JSON).
        csv_filepath : str
            Percorso a un CSV oppure a uno ZIP contenente uno o più CSV.
        field_name : str, opzionale
            Nome della colonna del CSV su cui agire. Se None, usa config["field"].
        """
        self.config = config
        if field_name is not None:
            self.field_name = field_name
        else:
            self.field_name = config["field"]
        self.csv_filepath = csv_filepath

        self.warning_cases: List[CaseConfig] = self._normalize_cases(
            config.get("warning", [])
        )
        self.error_cases: List[CaseConfig] = self._normalize_cases(
            config.get("error", [])
        )

    @staticmethod
    def _normalize_cases(raw_cases: Iterable[Any]) -> List[CaseConfig]:
        cases: List[CaseConfig] = []
        for entry in raw_cases:
            if isinstance(entry, str):
                cases.append(CaseConfig(label=entry, pattern=None))
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                label, pattern = entry
                cases.append(CaseConfig(label=str(label), pattern=str(pattern)))
            else:
                raise ValueError(f"Formato di caso non supportato: {entry!r}")
        return cases

    def evaluate_value(self, value: Optional[str]) -> Tuple[List[str], Dict[str, str]]:
        """
        Da implementare nelle classi figlie.
        """
        raise NotImplementedError

    def run(self, output_dir: Optional[str] = None) -> None:
        """
        Esegue la valutazione sul/i file CSV e genera i tre output.
        """
        # default se non specificato
        if output_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            output_dir = os.path.join(
                base_dir,
                "output_reports"
            )

        os.makedirs(output_dir, exist_ok=True)

        total_entities = 0
        files_considered: List[str] = []

        case_counter: Counter = Counter()
        warnings_detail: Dict[str, Counter] = defaultdict(Counter)
        errors_detail: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(
            lambda: defaultdict(lambda: {"subst": "", "count": 0})
        )

        for csv_file, reader in self._iter_csv_readers():
            files_considered.append(csv_file)

            try:
                header = next(reader)
            except StopIteration:
                continue

            if self.field_name not in header:
                continue

            idx = header.index(self.field_name)

            # converto il reader in lista per avere una barra di progresso
            rows = list(reader)
            progress = tqdm(rows, desc=f"Processing {self.field_name}", unit="row")

            for row in progress:
                if not row:
                    continue
                if idx >= len(row):
                    continue

                value = row[idx]
                total_entities += 1

                warnings, errors = self.evaluate_value(value)

                for w in warnings:
                    case_counter[(w, "warning")] += 1
                    warnings_detail[value][w] += 1

                for e_label, subst in errors.items():
                    case_counter[(e_label, "error")] += 1
                    e_info = errors_detail[value][e_label]
                    e_info["count"] += 1
                    if e_info["subst"] == "":
                        e_info["subst"] = subst

        self._write_summary_csv(
            output_dir, case_counter, total_entities, files_considered
        )
        self._write_warnings_csv(output_dir, warnings_detail)
        self._write_errors_csv(output_dir, errors_detail)

    def _iter_csv_readers(self) -> Iterable[Tuple[str, Iterable[List[str]]]]:
        path = self.csv_filepath
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".csv"):
                        continue
                    with zf.open(name, "r") as f:
                        reader = csv.reader(
                            (line.decode("utf-8", errors="replace") for line in f)
                        )
                        yield name, reader
        else:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                yield os.path.basename(path), reader

    def _write_summary_csv(
        self,
        output_dir: str,
        case_counter: Counter,
        total_entities: int,
        files_considered: List[str],
    ) -> None:
        out_path = os.path.join(output_dir, f"{self.field_name}_summary.csv")
        files_str = ";".join(files_considered)

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "case",
                    "case_type",
                    "total_occurrences",
                    "percentage_on_total_entities",
                    "files_considered",
                ]
            )

            first_row = True
            for (case_label, case_type), count in case_counter.items():
                if total_entities > 0:
                    percentage = (count / total_entities) * 100
                else:
                    percentage = 0.0

                files_val = files_str if first_row else ""
                first_row = False

                writer.writerow(
                    [
                        case_label,
                        case_type,
                        count,
                        f"{percentage:.4f}",
                        files_val,
                    ]
                )

    def _write_warnings_csv(
        self,
        output_dir: str,
        warnings_detail: Dict[str, Counter],
    ) -> None:
        out_path = os.path.join(output_dir, f"{self.field_name}_warnings.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["value", "case", "occurrences"])

            for value, case_counts in warnings_detail.items():
                case_labels = ";".join(sorted(case_counts.keys()))
                occurrences = sum(case_counts.values())
                writer.writerow([value, case_labels, occurrences])

    def _write_errors_csv(
        self,
        output_dir: str,
        errors_detail: Dict[str, Dict[str, Dict[str, Any]]],
    ) -> None:
        out_path = os.path.join(output_dir, f"{self.field_name}_errors.csv")
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["value", "case", "substitution_value", "occurrences"])

            for value, cases in errors_detail.items():
                sorted_labels = sorted(cases.keys())
                case_labels = ";".join(sorted_labels)
                subst_values = ";".join(cases[label]["subst"] for label in sorted_labels)
                occurrences = sum(cases[label]["count"] for label in sorted_labels)
                writer.writerow([value, case_labels, subst_values, occurrences])
