# app/utils/ollama.py
"""
Wrapper for invoking Ollama CLI commands and scraping to manage and chat with models.
"""
import subprocess
import re
from typing import List, Optional

# Optional imports for remote model listing
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

OLLAMA_CMD = "ollama"



def list_remote_models() -> List[str]:
    """Return models available from the Ollama registry including parameter variations.

    The function scrapes ``https://ollama.com/library`` to obtain the list of
    base model names. For each model, its dedicated page is fetched to search
    for all available variants (e.g. ``gemma3:1b``). If no variants are found,
    the base name is returned.
    """

    if not requests or not BeautifulSoup:
        raise RuntimeError(
            "Missing dependencies for remote model listing: requests, beautifulsoup4"
        )
    url = "https://ollama.com/library"
    resp = requests.get(url)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Error fetching remote models page: status {resp.status_code}"
        )
    soup = BeautifulSoup(resp.text, "html.parser")

    base_models: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]

        if href.startswith("/library/"):

            name = href.split("/")[-1]
            if name and name not in base_models:
                base_models.append(name)


    models: List[str] = []

    for name in base_models:
        variants = []
        try:
            detail = requests.get(f"https://ollama.com/library/{name}")
            if detail.status_code == 200:
                text = detail.text
                # Search for occurrences like "gemma3:1b" within the page
                pattern = rf"{name}:[^\"'\\s<]+"
                matches = set(re.findall(pattern, text, flags=re.IGNORECASE))
                variants.extend(sorted(matches))
        except Exception:
            pass


        if variants:
            models.extend(variants)
        else:
            models.append(name)

    return models


def list_remote_base_models() -> List[str]:
    """Return list of base model names available in the Ollama registry."""
    if not requests or not BeautifulSoup:
        raise RuntimeError(
            "Missing dependencies for remote model listing: requests, beautifulsoup4"
        )

    url = "https://ollama.com/library"
    resp = requests.get(url)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Error fetching remote models page: status {resp.status_code}"
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    models: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/library/"):
            name = href.split("/")[-1]
            if name and name not in models:
                models.append(name)
    return models


def list_model_variants(name: str) -> List[str]:
    """Return available variants for a given base model."""
    if not requests or not BeautifulSoup:
        raise RuntimeError(
            "Missing dependencies for remote model listing: requests, beautifulsoup4"
        )

    resp = requests.get(f"https://ollama.com/library/{name}")
    if resp.status_code != 200:
        raise RuntimeError(
            f"Error fetching model page for '{name}': status {resp.status_code}"
        )

    text = resp.text
    pattern = rf"{re.escape(name)}:[^\"'\\s<]+"
    matches = set(re.findall(pattern, text, flags=re.IGNORECASE))
    return sorted(matches) if matches else [name]


def list_installed_models() -> List[str]:
    """
    List models currently installed locally via Ollama CLI.
    Returns a list of model names.
    """
    result = subprocess.run(
        [OLLAMA_CMD, "list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error listing installed models: {result.stderr.strip()}")

    models: List[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if not parts or parts[0].lower() == "name":
            continue
        models.append(parts[0])
    return models


def install_model(name: str) -> None:
    """
    Install a model from the public registry by its name.
    Raises RuntimeError on failure.
    """
    result = subprocess.run(
        [OLLAMA_CMD, "pull", name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error installing model '{name}': {result.stderr.strip()}")


def remove_model(name: str) -> None:
    """
    Remove an installed model by its name.
    Tries `ollama rm` then `ollama remove`.
    Raises RuntimeError on failure.
    """
    # Try short alias
    result = subprocess.run(
        [OLLAMA_CMD, "rm", name],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return
    # Fallback
    result = subprocess.run(
        [OLLAMA_CMD, "remove", name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error removing model '{name}': {result.stderr.strip()}")


def chat(
    session_id: str,
    model: str,
    prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:

    # Формируем команду: ollama run <model> <prompt> [--temperature X] [--max-tokens Y]
    cmd = [OLLAMA_CMD, "run", model, prompt]
    if temperature is not None:
        cmd.extend(["--temperature", str(temperature)])
    if max_tokens is not None:
        cmd.extend(["--max-tokens", str(max_tokens)])

    # Запускаем процесс и получаем сырые байты
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # Декодируем stderr с учётом возможной кодировки
        try:
            err = result.stderr.decode("utf-8")
        except:
            err = result.stderr.decode("cp866", errors="ignore")
        raise RuntimeError(f"Error during chat with model '{model}': {err.strip()}")

    # Пытаемся декодировать stdout: сначала UTF-8, затем cp866, затем cp1251
    out_bytes = result.stdout
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            output = out_bytes.decode(enc)
            break
        except:
            continue
    else:
        output = out_bytes.decode("utf-8", errors="ignore")

    return output.strip()

