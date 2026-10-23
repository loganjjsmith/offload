import os


def _lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


class JobQueue:
    def __init__(self, path, max_attempts=1):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.path = path
        self.max_attempts = max_attempts
        self.done_path = path + ".done"
        self.failed_path = path + ".failed"

    def jobs(self):
        out = []
        for line in _lines(self.path):
            line = line.strip()
            if line and not line.startswith("#") and line not in out:
                out.append(line)
        return out

    def done(self):
        return {line.strip() for line in _lines(self.done_path) if line.strip()}

    def _failures(self):
        counts = {}
        for line in _lines(self.failed_path):
            if not line.strip():
                continue
            count, _, job = line.partition("\t")
            counts[job.strip()] = int(count)
        return counts

    def _write_failures(self, counts):
        with open(self.failed_path, "w", encoding="utf-8", newline="\n") as f:
            for job, count in counts.items():
                f.write(f"{count}\t{job}\n")

    def attempts(self, job):
        return self._failures().get(job, 0)

    def given_up(self):
        return [job for job, count in self._failures().items() if count >= self.max_attempts]

    def next_job(self):
        done, gone = self.done(), set(self.given_up())
        for job in self.jobs():
            if job not in done and job not in gone:
                return job
        return None

    def record(self, job, ok):
        if ok:
            if job not in self.done():
                with open(self.done_path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(job + "\n")
            return
        counts = self._failures()
        counts[job] = counts.get(job, 0) + 1
        self._write_failures(counts)

    def run(self, runner):
        results = []
        while (job := self.next_job()) is not None:
            try:
                ok = runner(job) == 0
            except Exception:
                ok = False
            self.record(job, ok)
            results.append((job, ok))
        return results

    def status(self):
        done, gone = self.done(), set(self.given_up())
        jobs = self.jobs()
        return {"pending": sum(1 for j in jobs if j not in done and j not in gone),
                "done": sum(1 for j in jobs if j in done),
                "given_up": sum(1 for j in jobs if j in gone)}

    def reset(self, job):
        counts = self._failures()
        if job in counts:
            del counts[job]
            self._write_failures(counts)
