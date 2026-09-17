"""Konfiguration laden - Konten, Ordner, Regeln, Passwoerter.

Passwoerter stehen nie in einer Datei dieses Repos. Sie kommen aus dem
macOS-Schluesselbund oder aus einer Umgebungsvariablen.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
CONFIG_DIR = WURZEL / "config"
STATE_DIR = WURZEL / "state"
RUNS_DIR = WURZEL / "runs"

# Standard-Ordnernamen je Rolle. Werden durch die Konto-Konfiguration und,
# wo moeglich, durch die Special-Use-Angaben des Servers ueberschrieben.
STANDARD_ORDNER = {
    "posteingang": "INBOX",
    "handeln": "Triage/1 Handeln",
    "wartet": "Triage/2 Wartet",
    "lesen": "Triage/3 Lesen",
    "archiv": "Archive",
    "papierkorb": "Deleted Messages",
    "spam": "Junk",
}


class ConfigError(RuntimeError):
    pass


@dataclass
class Konto:
    name: str
    host: str
    benutzer: str
    port: int = 993
    beschreibung: str = ""
    keychain_dienst: str = ""
    passwort_env: str = ""
    meine_adressen: tuple[str, ...] = ()
    ordner: dict[str, str] = field(default_factory=dict)
    quell_ordner: tuple[str, ...] = ("INBOX",)
    aktiv: bool = True

    def ordner_fuer(self, rolle: str) -> str:
        return self.ordner.get(rolle) or STANDARD_ORDNER.get(rolle) or "INBOX"

    def passwort(self) -> str:
        """Schluesselbund zuerst, dann Umgebungsvariable."""
        if self.keychain_dienst:
            treffer = _keychain(self.keychain_dienst, self.benutzer)
            if treffer:
                return treffer
        env_name = self.passwort_env or f"MAILTRIAGE_{self.name.upper()}_PASSWORT"
        wert = os.environ.get(env_name)
        if wert:
            return wert
        raise ConfigError(
            f"Kein Passwort fuer Konto {self.name!r}.\n"
            f"  Schluesselbund:  security add-generic-password -s "
            f"{self.keychain_dienst or 'mailtriage-' + self.name} "
            f"-a {self.benutzer} -w '<app-spezifisches-passwort>'\n"
            f"  oder Umgebung:   export {env_name}='<app-spezifisches-passwort>'"
        )


@dataclass
class Einstellungen:
    max_aktionen_pro_lauf: int = 800
    taegliches_fenster_tage: int = 7
    backlog_fenster_tage: int = 7
    bericht_max_zeilen: int = 320
    bericht_max_beispiele: int = 5
    bericht_top_absender: int = 20
    bericht_max_pruefen: int = 60


@dataclass
class Config:
    konten: list[Konto]
    einstellungen: Einstellungen
    regeln: list[dict]
    schutz: dict
    standard: dict

    def konto(self, name: str) -> Konto:
        for k in self.konten:
            if k.name == name:
                return k
        verfuegbar = ", ".join(k.name for k in self.konten)
        raise ConfigError(f"Konto {name!r} nicht gefunden. Verfuegbar: {verfuegbar}")

    def aktive_konten(self) -> list[Konto]:
        return [k for k in self.konten if k.aktiv]


def _keychain(dienst: str, konto: str) -> str | None:
    """Passwort aus dem macOS-Schluesselbund. Ausserhalb von macOS: None."""
    try:
        ergebnis = subprocess.run(
            ["security", "find-generic-password", "-s", dienst, "-a", konto, "-w"],
            capture_output=True, text=True, timeout=20, check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return ergebnis.stdout.strip() or None if ergebnis.returncode == 0 else None


def _lade_json(pfad: Path, was: str) -> dict:
    if not pfad.exists():
        beispiel = pfad.with_name(pfad.stem + ".beispiel.json")
        hinweis = f"\n  Vorlage kopieren:  cp {beispiel} {pfad}" if beispiel.exists() else ""
        raise ConfigError(f"{was} fehlt: {pfad}{hinweis}")
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{was} ist kein gueltiges JSON ({pfad}): {exc}") from exc


def lade(konten_pfad: Path | None = None, regel_pfad: Path | None = None) -> Config:
    konten_pfad = konten_pfad or CONFIG_DIR / "konten.json"
    regel_pfad = regel_pfad or CONFIG_DIR / "regeln.json"

    roh_konten = _lade_json(konten_pfad, "Kontenkonfiguration")
    roh_regeln = _lade_json(regel_pfad, "Regelwerk")

    konten: list[Konto] = []
    for eintrag in roh_konten.get("konten", []):
        fehlend = [f for f in ("name", "host", "benutzer") if not eintrag.get(f)]
        if fehlend:
            raise ConfigError(
                f"Konto in {konten_pfad} unvollstaendig, es fehlt: {', '.join(fehlend)}")
        if "passwort" in eintrag:
            raise ConfigError(
                f"Konto {eintrag['name']!r} enthaelt ein Feld 'passwort'. "
                "Passwoerter gehoeren in den Schluesselbund, nicht in diese Datei."
            )
        konten.append(Konto(
            name=eintrag["name"],
            host=eintrag["host"],
            benutzer=eintrag["benutzer"],
            port=int(eintrag.get("port", 993)),
            beschreibung=eintrag.get("beschreibung", ""),
            keychain_dienst=eintrag.get("keychain_dienst", f"mailtriage-{eintrag['name']}"),
            passwort_env=eintrag.get("passwort_env", ""),
            meine_adressen=tuple(a.lower() for a in eintrag.get("meine_adressen", [])),
            ordner={**eintrag.get("ordner", {})},
            quell_ordner=tuple(eintrag.get("quell_ordner", ["INBOX"])),
            aktiv=bool(eintrag.get("aktiv", True)),
        ))

    if not konten:
        raise ConfigError(f"Keine Konten in {konten_pfad} definiert.")

    bekannt = {f.name for f in Einstellungen.__dataclass_fields__.values()}
    roh_einst = {k: v for k, v in roh_konten.get("einstellungen", {}).items() if k in bekannt}

    return Config(
        konten=konten,
        einstellungen=Einstellungen(**roh_einst),
        regeln=roh_regeln.get("regeln", []),
        schutz=roh_regeln.get("schutz", {}),
        standard=roh_regeln.get("standard", {"kategorie": "unklar", "aktion": "pruefen"}),
    )
