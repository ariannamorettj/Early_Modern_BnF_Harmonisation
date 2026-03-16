import json
import os
import re
from typing import List, Dict, Optional, Tuple

from evaluation_base import Evaluation


class PersonNameEvaluation(Evaluation):
    """
    Evaluator per campi che contengono nomi di persona.
    Usa la configurazione JSON person_names.json e una serie di regole
    specializzate per warning ed errori.
    """

    PARTICLES = {"de", "da", "di", "del", "van", "von", "y", "e", "et", "und"}
    CONJUNCTIONS = {"e", "and", "et", "y", "und"}
    ROMAN_NUMERAL_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)

    def __init__(
        self,
        csv_filepath: str,
        csv_field_name: str,
        config_path: Optional[str] = None,
    ):
        """
        Parameters
        ----------
        csv_filepath : str
            Percorso al CSV (o ZIP) da valutare.
        csv_field_name : str
            Nome della colonna del CSV su cui eseguire la valutazione
            (es. 'actor_name', 'actor_first_name', 'actor_last_name').
        config_path : str, opzionale
            Percorso al file JSON di configurazione. Se None, usa il default.
        """
        if config_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(
                base_dir,
                "input_harmonising_dicts",
                "person_names.json",
            )

        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        super().__init__(config, csv_filepath, field_name=csv_field_name)

        # logica specifica per warning
        self._warning_logic = {
            "initials only": self._is_initials_only,
            "dotted initials only": self._is_dotted_initials_only,
            "undefined number of undeciphered characters": self._has_undefined_undeciphered_chars,
            "possibly missing name or surname": self._is_single_token,
            "possibly contains multiple values": self._contains_multiple_values,
            "probably contains alternative names": self._contains_alias_word,
            "possibly contains an article (in the place of or in addition to the name)": self._ends_with_article,
            "possibly contains a preposition (in the place of or in addition to the name)": self._ends_with_preposition,
            "possible abbreviation": self._is_possible_abbreviation,
            "contain possible personal title or role": self._contains_title_or_role,
            "possibly contains only part of multiple values": self._contains_partial_multiple_values,
            "possibly contains a Roman numeral (in the place of or in addition to the name)": self._ends_with_roman_numeral,
            "contains also dotted initials": self._contains_also_dotted_initials,
        }

        # logica specifica per errori
        self._error_logic = {
            "missing value": self._error_missing_value,
            "contains number (non-Roman)": self._error_contains_number_non_roman,
            "contains non-alphanumerical characters (excluding * and .)": self._error_non_alphanum_excl_star_dot,
            "contains null marker": self._error_null_marker,
            "contains brackets or surrounding separators": self._error_brackets_or_separators,
        }

    # ------------------------------------------------------------------ #
    # API chiamata dalla classe base per ciascun valore
    # ------------------------------------------------------------------ #

    def evaluate_value(self, value: Optional[str]) -> Tuple[List[str], Dict[str, str]]:
        warnings: List[str] = []
        errors: Dict[str, str] = {}

        if value is None:
            value = ""
        stripped = value.strip()

        if stripped == "":
            return warnings, errors

        # --------------------------- WARNING -----------------------------

        for case in self.warning_cases:
            label = case.label
            logic_fn = self._warning_logic.get(label)

            if logic_fn is not None:
                if logic_fn(stripped):

                    # disattiva "possibly missing name or surname" per first/last name
                    if (
                        label == "possibly missing name or surname"
                        and self.field_name in ("actor_first_name", "actor_last_name")
                    ):
                        pass

                    # evita "initials only" se è già "dotted initials only"
                    elif (
                        label == "initials only"
                        and "dotted initials only" in warnings
                    ):
                        pass

                    else:
                        warnings.append(label)

                # se c'è una logica specifica, non usiamo la regex per questo label
                continue

            # fallback: usa la regex se presente e non esiste logica specifica
            if case.pattern:
                if re.search(case.pattern, stripped):
                    warnings.append(label)

        # deduplica mantenendo l'ordine
        warnings = list(dict.fromkeys(warnings))

        # ---------------------------- ERROR ------------------------------

        for case in self.error_cases:
            label = case.label
            logic_fn = self._error_logic.get(label)

            substitution: Optional[str] = None

            if logic_fn is not None:
                substitution = logic_fn(stripped)

            if substitution is None and case.pattern:
                if re.search(case.pattern, stripped):
                    substitution = ""

            if substitution is not None:
                errors[label] = substitution

        return warnings, errors

    # ------------------------------------------------------------------ #
    # Funzioni di supporto per warning
    # ------------------------------------------------------------------ #

    def _tokenize(self, value: str) -> List[str]:
        return [t for t in value.split() if t]

    def _is_initials_only(self, value: str) -> bool:
        """
        Casi tipo: 'M D', 'M D P', 'G de M'.

        Requisiti:
        - almeno 2 token (evita 'Jo');
        - ignora particelle (de, di, von, van, ecc.);
        - ogni token significativo ha lunghezza <= 2;
        - se è "dotted initials only" (es. 'G.'), non entra qui.
        """
        if self._is_dotted_initials_only(value):
            return False

        tokens = self._tokenize(value)
        if len(tokens) < 2:
            return False

        has_initial = False
        for tok in tokens:
            t = tok.strip(".")
            if not t:
                continue
            if t.lower() in self.PARTICLES:
                continue
            if len(t) <= 2:
                has_initial = True
                continue
            return False
        return has_initial

    def _is_dotted_initials_only(self, value: str) -> bool:
        """
        Casi tipo: 'M.', 'M. B. L.', 'M. Th. A. B.', 'D.j.', 'A. S.', 'L.J.'.

        - 'G.' -> solo 'dotted initials only'
        - 'L.J.' -> 'dotted initials only'
        - 'Th.' (2 lettere + punto) -> 'possible abbreviation', non dotted initials.
        """
        tokens = self._tokenize(value)
        if not tokens:
            return False

        # singolo token tipo 'L.J.'
        if len(tokens) == 1 and re.fullmatch(r"[A-Za-z]\.[A-Za-z]\.", tokens[0]):
            return True

        # singolo token tipo 'Th.' -> abbreviato, non dotted initials only
        if len(tokens) == 1 and re.fullmatch(r"[A-Za-z]{2,3}\.", tokens[0]):
            return False

        pattern = re.compile(r"^[A-Za-z]{1,2}\.$")
        for tok in tokens:
            if not pattern.match(tok):
                return False
        return True

    def _has_undefined_undeciphered_chars(self, value: str) -> bool:
        return bool(re.search(r"\.{3,}", value))

    def _is_single_token(self, value: str) -> bool:
        tokens = self._tokenize(value)
        return len(tokens) == 1

    def _contains_alias_word(self, value: str) -> bool:
        """
        'probably contains alternative names'

        - Casi con 'alias'
        - Casi francesi tipo 'plus connu ss le n de', 'plus connu sous le nom de'
        - Casi tipo 'dit il', 'detto il' e traduzioni principali
        """
        lower = value.lower()

        # alias classico
        if re.search(r"\balias\b", lower):
            return True

        # 'plus connu ...'
        if "plus connu" in lower:
            if "ss le n de" in lower:
                return True
            if "sous le nom de" in lower:
                return True

        # marker di alias in varie lingue
        alias_markers = [
            "dit il",
            "dit le",
            "dit la",
            "detto il",
            "detto lo",
            "detto la",
            "detta la",
            "called ",
            "called the",
            "also known as",
            "known as",
            "surnommé",
            "surnommee",
            "llamado",
            "llamada",
            "conocido como",
            "conocida como",
            "apodado",
            "apodada",
            "genannt",
            "bekannt als",
        ]
        if any(m in lower for m in alias_markers):
            return True

        return False

    def _ends_with_article(self, value: str) -> bool:
        """
        'possibly contains an article ...' se la stringa FINISCE con un articolo.
        Per il caso 'Julien I', trattiamo 'I' come ambiguo e lo segnaliamo anche qui.
        """
        tokens = self._tokenize(value.lower())
        if not tokens:
            return False

        last = tokens[-1]
        last_two = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""

        articles_single = {
            # francese
            "le", "la", "les", "l'",
            # italiano
            "il", "lo", "gli", "i", "la", "le",
            # spagnolo
            "el", "la", "los", "las",
            # inglese
            "the",
            # tedesco
            "der", "die", "das",
        }

        articles_multi = set()

        if last in articles_single:
            return True
        if last_two in articles_multi:
            return True

        # caso ambiguo 'I' (come 'Julien I')
        last_clean = re.sub(r"[^\w]", "", tokens[-1]).upper()
        if last_clean == "I":
            return True

        return False

    def _ends_with_preposition(self, value: str) -> bool:
        """
        'possibly contains a preposition ...' se la stringa FINISCE con
        una preposizione / articolo partitivo (fr/it/en/es/de) o 'van'/'von'.
        """
        tokens = self._tokenize(value.lower())
        if not tokens:
            return False

        last = tokens[-1]
        last_two = " ".join(tokens[-2:]) if len(tokens) >= 2 else ""

        preps_single = {
            "de", "d", "d'", "du", "des",
            "di", "del", "della", "dei", "degli",
            "da",
            "of", "from",
            "van", "von",
        }

        preps_multi = {
            "de la", "de los", "de las",
            "of the",
        }

        if last in preps_single:
            return True
        if last_two in preps_multi:
            return True
        return False

    def _is_possible_abbreviation(self, value: str) -> bool:
        tokens = self._tokenize(value)
        if len(tokens) != 1:
            return False
        # 2–3 lettere + punto, es. 'Th.'
        return bool(re.fullmatch(r"[A-Za-z]{2,3}\.", tokens[0]))

    def _contains_title_or_role(self, value: str) -> bool:
        """
        Titoli e ruoli: Veuve/Vve/Vve de, en religion, seigneur, sieur de,
        chevalier, comte/comtesse, duque/duc, cardinal, prince,
        officier/officer, colonel, dame/donna/lady, abbé/abate/abbot,
        'le fils du', 'son of', ecc.

        ATTENZIONE: la parola del titolo deve essere token separato,
        non parte di un'altra parola (quindi 'Duchâtel' non conta per 'duc').
        """
        lower = value.lower()
        tokens = self._tokenize(lower)

        single_word_titles = {
            "veuve", "vve", "seigneur", "sieur", "prince",
            "chevalier", "comte", "comtesse",
            "duque", "duc",
            "cardinal",
            "officier", "officer",
            "colonel",
            "dame", "madame", "mme",
            "abbé", "abbe", "abate", "abbot",
            "herr", "frau",
            "rey", "reina",
            "king", "queen",
        }

        multi_word_titles = {
            "vve de",
            "veuve de",
            "widow of",
            "vedova di",
            "viuda de",
            "witwe von",
            "sieur de",
            "le fils du",
            "fils de",
            "son of",
            "hijo de",
            "figlio di",
            "homme de lettres",
        }

        # controllo parole singole
        if any(tok in single_word_titles for tok in tokens):
            return True

        # controllo frasi multi-token
        if tokens:
            for i in range(len(tokens) - 1):
                bigram = tokens[i] + " " + tokens[i + 1]
                if bigram in multi_word_titles:
                    return True
            for i in range(len(tokens) - 2):
                trigram = tokens[i] + " " + tokens[i + 1] + " " + tokens[i + 2]
                if trigram in multi_word_titles:
                    return True

        return False

    def _is_compound_spanish_like(self, tokens: List[str]) -> bool:
        """
        Riconosce pattern tipo:
        'Fernando Álvarez de Toledo y Pimentel',
        'Francisco Gómez de Sandoval y Rojas',
        'Juan de Tassis y Peralta'.

        Schema: ... PREP ... CONJ ...
        con PREP in {de, del, de la, de los, de las, di, da, of}.
        """
        lower_tokens = [t.lower() for t in tokens]
        if len(lower_tokens) < 4:
            return False

        preps = {"de", "del", "de la", "de los", "de las", "di", "da", "of"}

        for i in range(len(lower_tokens)):
            if lower_tokens[i] in preps:
                # cerca una congiunzione dopo la prep
                for j in range(i + 1, len(lower_tokens) - 1):
                    if lower_tokens[j] in self.CONJUNCTIONS:
                        # deve esserci almeno un token dopo la congiunzione
                        if j + 1 < len(lower_tokens):
                            return True
        return False

    def _contains_multiple_values(self, value: str) -> bool:
        """
        'possibly contains multiple values'

        Regole:
        - 'E Matthaeus' (congiunzione all'inizio, 2 token) -> NON multiplo
        - 'Martinus And' (congiunzione alla fine) -> NON multiplo (gestito
          da 'possibly contains only part of multiple values')
        - pattern tipo 'Fernando Álvarez de Toledo y Pimentel' -> NON multiplo
        - 'Les frères' e analoghi -> multiplo
        - congiunzione interna generica -> multiplo
        """
        lower = value.lower().strip()
        tokens = self._tokenize(lower)
        if not tokens:
            return False

        # "Les frères" e analoghi
        group_phrases = [
            "les freres",
            "les frères",
            "the brothers",
            "i fratelli",
            "los hermanos",
            "die brüder",
            "die bruder",
        ]
        for phrase in group_phrases:
            if lower.startswith(phrase):
                return True

        # 'E Matthaeus' e simili: 2 token, primo è congiunzione -> non multiplo
        if len(tokens) == 2 and tokens[0] in self.CONJUNCTIONS:
            return False

        # 'Martinus And' ecc. -> non multiplo (gestito a parte)
        if tokens[-1] in self.CONJUNCTIONS:
            return False

        # pattern tipo 'Fernando Álvarez de Toledo y Pimentel'
        if self._is_compound_spanish_like(tokens):
            return False

        # caso generico: congiunzione interna -> multiplo
        for tok in tokens:
            if tok in self.CONJUNCTIONS:
                return True

        return False

    def _contains_partial_multiple_values(self, value: str) -> bool:
        """
        'possibly contains only part of multiple values':
        es. 'Martinus And', 'Mario e', 'Hans und' (congiunzione finale).
        """
        lower = value.lower().strip()
        tokens = self._tokenize(lower)
        if len(tokens) >= 2 and tokens[-1] in self.CONJUNCTIONS:
            return True
        return False

    def _ends_with_roman_numeral(self, value: str) -> bool:
        """
        'possibly contains a Roman numeral ...' se la stringa FINISCE
        con un numero romano (token finale).
        Esempio: 'Julien I' -> numero romano.
        """
        tokens = self._tokenize(value)
        if not tokens:
            return False
        last = tokens[-1]
        # ignoriamo punteggiatura finale
        last_clean = re.sub(r"[^\w]", "", last).upper()
        if not last_clean:
            return False
        return bool(self.ROMAN_NUMERAL_RE.fullmatch(last_clean))

    def _contains_also_dotted_initials(self, value: str) -> bool:
        """
        'contains also dotted initials':
        casi come "A.b.c.d.e.f.g.h.i.k.l.m.n.o.p.q.r.s.t.u.x.y.z. &c, opticien des Quinze-Vingts":
        ovvero sequenze di iniziali puntate + altre parole.
        """
        # se è solo dotted initials, non entra qui
        if self._is_dotted_initials_only(value):
            return False

        lower = value.lower()

        # cerca sequenze tipo A.b.c. o M. B. L. (dotted initials)
        has_dotted_sequence = bool(re.search(r"(?:[a-z]\.){2,}", lower))
        has_dotted_token = bool(re.search(r"\b[a-z]\.", lower))

        # cerca almeno una parola "normale" (>= 2 lettere)
        has_word = bool(re.search(r"\b[a-z]{2,}\b", lower))

        return (has_dotted_sequence or has_dotted_token) and has_word

    # ------------------------------------------------------------------ #
    # Funzioni di supporto per errori (ritornano substitution o None)
    # ------------------------------------------------------------------ #

    def _error_missing_value(self, value: str) -> Optional[str]:
        if value.strip() == "***":
            return ""
        return None

    def _contains_number_non_roman(self, value: str) -> bool:
        if not re.search(r"\d", value):
            return False
        if self.ROMAN_NUMERAL_RE.fullmatch(value.strip()):
            return False
        return True

    def _error_contains_number_non_roman(self, value: str) -> Optional[str]:
        if self._contains_number_non_roman(value):
            return ""
        return None

    def _contains_non_alphanum_excl_star_dot(self, value: str) -> bool:
        return bool(re.search(r"[^\w\s\*\.]", value))

    def _error_non_alphanum_excl_star_dot(self, value: str) -> Optional[str]:
        if self._contains_non_alphanum_excl_star_dot(value):
            return ""
        return None

    def _contains_null_marker(self, lower_value: str) -> bool:
        return bool(re.search(r"\b(null|nan)\b", lower_value))

    def _error_null_marker(self, value: str) -> Optional[str]:
        if self._contains_null_marker(value.lower()):
            return ""
        return None

    def _contains_brackets_or_separators(self, value: str) -> bool:
        # include [], (), {}, "", <>, e //
        separators = "[](){}\"<>"
        if any(ch in value for ch in separators):
            return True
        if "//" in value:
            return True
        return False

    def _strip_wrapping_punctuation(self, value: str) -> str:
        s = value.strip()
        if not s:
            return s

        pairs = {
            "[": "]",
            "(": ")",
            "{": "}",
            "«": "»",
            "<": ">",
            '"': '"',
            "'": "'",
        }

        first, last = s[0], s[-1]
        if first in pairs and last == pairs[first]:
            s = s[1:-1].strip()

        while s and not s[0].isalnum():
            s = s[1:].lstrip()
        while s and not s[-1].isalnum():
            s = s[:-1].rstrip()

        return s

    def _error_brackets_or_separators(self, value: str) -> Optional[str]:
        if not self._contains_brackets_or_separators(value):
            return None
        cleaned = self._strip_wrapping_punctuation(value)
        if cleaned != value:
            return cleaned
        return None
