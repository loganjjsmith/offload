"""Coding to spec in Python, TypeScript and C#, scored by hidden tests in a Docker sandbox.

The problems in coding/*.yaml were written for this project on 2026-10-15, after every
candidate model was released, so no model can have memorised them.
"""
import re
from pathlib import Path

import yaml
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer, stderr
from inspect_ai.solver import generate, system_message
from inspect_ai.util import sandbox

HERE = Path(__file__).parent
LANGUAGES = {"python": "python.yaml", "typescript": "typescript.yaml", "csharp": "csharp.yaml"}
FENCES = {"python": ("python", "py"), "typescript": ("typescript", "ts"), "csharp": ("csharp", "cs", "c#")}
RUN_TIMEOUT_S = 120

SYSTEM = ("You are an expert programmer. Answer with the complete solution in a single fenced code "
          "block in the requested language, and nothing that would stop it compiling. Do not include "
          "tests, a main function or example usage.")

# Terse working mode: the same problems, answered as compactly as the language allows. A
# formatter re-expands the result, so only correctness and token count matter here.
TERSE = (" Write the code as compactly as possible: no comments, no docstrings, no blank lines, and "
         "for C# and TypeScript put everything on as few lines as the language allows. Keep names meaningful.")

CS_CHECK =('static void Check(bool ok, string what) { if (!ok) { System.Console.Error.WriteLine("FAIL: " + what); '
            'System.Environment.Exit(1); } }\n')


def problems(language=None):
    out = []
    for lang, file in LANGUAGES.items():
        if language and lang != language:
            continue
        for p in yaml.safe_load((HERE / "coding" / file).read_text(encoding="utf-8")):
            out.append(dict(p, language=lang))
    return out


def extract_code(text, language):
    """The last fenced block in the answer, preferring one tagged with the language."""
    blocks = re.findall(r"```([\w#+-]*)[ \t]*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        return text.strip()
    tagged = [code for tag, code in blocks if tag.lower() in FENCES[language]]
    return (tagged or [code for _, code in blocks])[-1]


def assemble(language, solution, tests):
    """Files to write and the command that runs the tests; exit code 0 means pass."""
    if language == "python":
        return {"solution.py": solution, "test_solution.py": tests}, ["python3", "test_solution.py"]
    if language == "typescript":
        return {"solution.mts": solution, "test.mts": tests}, ["node", "test.mts"]
    usings = [line for line in solution.splitlines() if re.match(r"\s*using\s+[\w.]+\s*;", line)]
    body = "\n".join(line for line in solution.splitlines() if line not in usings)
    program = "\n".join(usings) + "\n" + tests + "\n" + CS_CHECK + "\n" + body + "\n"
    return {"Program.cs": program}, ["dotnet", "run", "Program.cs"]


@scorer(metrics=[accuracy(), stderr()])
def hidden_tests():
    async def score(state, target):
        language = state.metadata["language"]
        code = extract_code(state.output.completion, language)
        files, command = assemble(language, code, state.metadata["tests"])
        box = sandbox()
        workdir = f"/work/{state.sample_id}"
        await box.exec(["mkdir", "-p", workdir])
        for name, content in files.items():
            await box.write_file(f"{workdir}/{name}", content)
        try:
            result = await box.exec(command, cwd=workdir, timeout=RUN_TIMEOUT_S)
            passed, detail = result.returncode == 0, (result.stdout + result.stderr)[-1500:]
        except TimeoutError:
            passed, detail = False, "timed out"
        return Score(value=CORRECT if passed else INCORRECT, answer=code[-3000:], explanation=detail)

    return score


@task
def coding(language: str | None = None, terse: bool = False):
    samples = [Sample(id=p["id"], input=p["prompt"], metadata={"language": p["language"], "tests": p["tests"]})
               for p in problems(language)]
    return Task(
        dataset=MemoryDataset(samples),
        solver=[system_message(SYSTEM + (TERSE if terse else "")), generate()],
        scorer=hidden_tests(),
        sandbox=("docker", str(HERE / "sandbox" / "compose.yaml")),
    )
