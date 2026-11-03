"""Sample courses for `study --demo`, laid out around today so every part of the UI has something to show."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from .models import (Course, Deadline, DeadlineKind, Exam, ExamQuestion, Priority, Project, ProjectEntry, ProjectLink,
                     ProjectNote, ProjectSource, ProjectTask, Session, Source, Topic, TopicStatus, WeakSpot)
from .storage import Store

NS, IP, RV, CF = TopicStatus.NOT_STARTED, TopicStatus.IN_PROGRESS, TopicStatus.REVIEWED, TopicStatus.CONFIDENT

# (code, name, cram start offset, exam offset, [(topic, status, confidence, studied days ago or None)])
COURSES = [
    ("DAT255", "Data Engineering", -25, 2, [
        ("Batch vs stream processing", CF, 5, 3), ("Spark internals", RV, 4, 2), ("Data modelling", RV, 4, 6),
        ("Kafka", IP, 3, 1), ("Orchestration with Airflow", RV, 3, 4), ("Data quality", NS, 1, None),
    ]),
    ("STK310", "Statistical Inference", -10, 24, [
        ("Likelihood", CF, 5, 2), ("Sufficiency", CF, 4, 5), ("Exponential families", RV, 4, 3),
        ("Hypothesis testing", RV, 3, 1), ("Bayesian inference", IP, 2, 0), ("Bootstrap", NS, 1, None),
    ]),
    ("INF301", "Machine Learning", -20, 12, [
        ("Linear models", CF, 5, 9), ("Regularisation", RV, 4, 8), ("Kernels and SVMs", IP, 2, 1),
        ("Trees and boosting", IP, 3, 4), ("Probabilistic models", NS, 1, None), ("Model selection", RV, 3, 11),
        ("Neural networks", NS, 1, None), ("Unsupervised learning", NS, 1, None),
    ]),
    ("INF395", "Deep Learning", 3, 40, [
        ("Backpropagation", IP, 2, 6), ("CNNs", NS, 1, None), ("Transformers", NS, 1, None),
    ]),
]

WEAK = [
    ("INF301", "Kernels and SVMs", "Can't derive the dual form of the SVM without notes", Priority.HIGH, 6),
    ("INF301", "Model selection", "Mixing up when to use nested cross-validation", Priority.MED, 3),
    ("STK310", "Sufficiency", "Factorisation theorem proofs", Priority.HIGH, 2),
    ("DAT255", "Kafka", "Exactly-once semantics", Priority.MED, 8),
    ("STK310", "Bayesian inference", "Conjugate priors beyond beta-binomial", Priority.LOW, 1),
]

# (course code, source title, author, [(chapter, title, topic, sections, read up to, optional sections)])
READING = [
    ("INF301", "Pattern recognition and machine learning", "Bishop, Christopher M.", [
        ("3", "Linear Models for Regression", "Linear models", "3.1-3.5", 5, ["3.4"]),
        ("6", "Kernel Methods", "Kernels and SVMs", "6.1-6.4", 2, ["6.4"]),
        ("7", "Sparse Kernel Machines", "Kernels and SVMs", "7.1-7.2", 0, ["7.2"]),
        ("14", "Combining Models", "Trees and boosting", "14.1-14.5", 3, []),
    ]),
    ("INF301", "Lecture notes", "", [
        ("5", "Model selection", "Model selection", "5.1-5.3", 3, []),
    ]),
    ("STK310", "Statistical inference", "Casella, George; Berger, Roger L.", [
        ("6", "Principles of Data Reduction", "Sufficiency", "6.1-6.4", 2, ["6.4"]),
        ("7", "Point Estimation", "Likelihood", "7.1-7.3", 3, []),
        ("8", "Hypothesis Testing", "Hypothesis testing", "8.1-8.3", 1, []),
    ]),
]

# Reference details for the sources above, so "Copy APA" has something to show.
CITATIONS = {
    "Pattern recognition and machine learning": {"year": "2006", "publisher": "Springer"},
    "Statistical inference": {"year": "2002", "edition": "2", "publisher": "Duxbury"},
    "Lecture notes": {"kind": "notes", "year": "2026", "publisher": "University of Bergen"},
}

# (course code or None, title, kind, due offset in hours, done)
DEADLINES = [
    ("INF301", "Problem set 4", DeadlineKind.ASSIGNMENT, 30, False),
    ("STK310", "Mandatory assignment 2", DeadlineKind.ASSIGNMENT, 5 * 24 + 3, False),
    ("DAT255", "Pipeline project report", DeadlineKind.ASSIGNMENT, -20, False),
    ("INF301", "Problem set 3", DeadlineKind.ASSIGNMENT, -6 * 24, True),
    (None, "Thesis outline to supervisor", DeadlineKind.MILESTONE, 15 * 24, False),
]

# (course code, exam title, kind, taken on, score, [(number, topic, marks, result, note, prompt, answer, why)])
EXAMS = [
    ("INF301", "Exam spring 2025", "past", "June 2025", "61/100", [
        ("1a", "Linear models", "8", "ok", "",
         "Show that the least-squares estimate for linear regression is $\\hat{w} = (X^\\top X)^{-1} X^\\top y$.",
         "Set the gradient of $\\lVert y - Xw \\rVert^2$ to zero: $-2X^\\top(y - Xw) = 0$, so $X^\\top X w = X^\\top y$.", ""),
        ("1b", "Regularisation", "7", "partial", "Got the ridge solution but not why it is always invertible.",
         "Add an $L_2$ penalty $\\lambda \\lVert w \\rVert^2$. Derive the new estimate and explain why it always exists for $\\lambda > 0$.",
         "$\\hat{w} = (X^\\top X + \\lambda I)^{-1} X^\\top y$. $X^\\top X$ is positive semi-definite, so adding $\\lambda I$ "
         "makes every eigenvalue at least $\\lambda > 0$: the matrix is invertible.", ""),
        ("2", "Kernels and SVMs", "15", "missed", "Couldn't set up the Lagrangian for the dual.",
         "Derive the dual of the hard-margin SVM\n\n$$\\min_{w,b} \\tfrac12 \\lVert w \\rVert^2 \\quad \\text{s.t.} \\quad "
         "y_n(w^\\top x_n + b) \\ge 1.$$",
         "Lagrangian $L = \\tfrac12\\lVert w\\rVert^2 - \\sum_n a_n\\{y_n(w^\\top x_n + b) - 1\\}$. Setting derivatives to zero gives "
         "$w = \\sum_n a_n y_n x_n$ and $\\sum_n a_n y_n = 0$, so the dual is\n\n$$\\max_a \\sum_n a_n - \\tfrac12 \\sum_{n,m} a_n a_m y_n y_m "
         "x_n^\\top x_m, \\quad a_n \\ge 0.$$", ""),
        ("3", "Model selection", "10", "partial", "Mixed up the inner and outer loops of nested cross-validation.",
         "Explain nested cross-validation and when you need it.",
         "The inner loop picks hyperparameters; the outer loop estimates the error of the whole procedure, "
         "so the estimate isn't biased by the tuning.", ""),
        ("4", "Trees and boosting", "10", "", "",
         "Explain how AdaBoost reweights the training points after each round.",
         "Misclassified points get their weight multiplied by $e^{\\alpha_m}$, then the weights are normalised.", ""),
    ]),
    ("INF301", "Practice exam 1: kernels and model selection", "practice", "", "", [
        ("1", "Kernels and SVMs", "10", "", "",
         "Show that $k(x, z) = (x^\\top z + 1)^2$ is a valid kernel for $x, z \\in \\mathbb{R}^2$ by writing out its feature map.",
         "$\\phi(x) = (1, \\sqrt2 x_1, \\sqrt2 x_2, x_1^2, \\sqrt2 x_1 x_2, x_2^2)$, and $k(x,z) = \\phi(x)^\\top\\phi(z)$.",
         "Practises the kernel algebra behind the SVM dual you missed in question 2 of the spring 2025 exam."),
        ("2", "Model selection", "8", "", "",
         "You tune $C$ for an SVM with 5-fold cross-validation and report the best score. Why is that score optimistic, "
         "and how would you fix it?",
         "The same folds chose $C$ and measured it. Use nested cross-validation: tune inside each outer training fold.",
         "Targets the mix-up between inner and outer loops from question 3 of the spring 2025 exam."),
    ]),
]


PROJECT = {
    "title": "Uncertainty in small language models",
    "description": "Master's thesis: do **calibration** methods that work for large models still help below 1B "
                   "parameters? Supervisor meetings every other Thursday.",
    "tags": ["thesis", "nlp", "calibration"],
    "notes": [
        ("Research questions", "1. Does temperature scaling stay well calibrated after fine-tuning?\n"
                               "2. How does the expected calibration error\n\n"
                               "$$\\mathrm{ECE} = \\sum_{m=1}^{M} \\frac{|B_m|}{n} \\left| \\mathrm{acc}(B_m) - "
                               "\\mathrm{conf}(B_m) \\right|$$\n\nchange with model size?", 6),
        ("Meeting 31 Oct", "- Use **three seeds** per run\n- Look at Guo et al. for the reliability diagrams\n"
                           "- Next: baseline on SST-2", 3),
    ],
    "entries": [
        (5, "Set up the training repo and a Colab notebook. Baseline runs on a T4 in about 40 minutes."),
        (2, "Baseline on SST-2: accuracy 0.91, **ECE 0.064**. Temperature scaling brings it to 0.021."),
        (0, "Started the label-smoothing runs. Seed 2 diverged; lowered the learning rate to `2e-5`."),
    ],
    "links": [
        ("Thesis draft", "https://www.overleaf.com/project/demo", ""),
        ("Zotero library", "zotero://select/library/collections/THESIS", ""),
        ("Code", "https://github.com/example/calibration", ""),
        ("Training notebook", "https://colab.research.google.com/drive/demo", ""),
        ("SST-2 dataset", "https://huggingface.co/datasets/stanfordnlp/sst2", ""),
        ("Google Scholar", "https://scholar.google.com/", ""),
    ],
    "sources": [
        ("On calibration of modern neural networks", "Guo, Chuan; Pleiss, Geoff; Sun, Yu; Weinberger, Kilian Q.",
         "2017", "https://arxiv.org/abs/1706.04599", "read", "Temperature scaling; reliability diagrams."),
        ("When does label smoothing help?", "Müller, Rafael; Kornblith, Simon; Hinton, Geoffrey", "2019",
         "https://arxiv.org/abs/1906.02629", "reading", ""),
        ("Calibration of pre-trained transformers", "Desai, Shrey; Durrett, Greg", "2020",
         "10.18653/v1/2020.emnlp-main.21", "to_read", ""),
    ],
    "tasks": [("Baseline on SST-2", True), ("Label smoothing runs (3 seeds)", False),
              ("Reliability diagrams for chapter 4", False), ("Send draft outline to supervisor", False)],
}


def seed(store: Store, now: datetime | None = None) -> None:
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    today = now.date()
    topic_ids: dict[tuple[str, str], int] = {}
    started: set[tuple[str, str]] = set()  # sessions go to topics studied in the last week, so older ones stay stale
    courses: dict[str, Course] = {}

    for code, name, start, exam, topics in COURSES:
        course = store.add_course(Course(name, code, today + timedelta(days=start), today + timedelta(days=exam),
                                         color=store.next_color()))
        courses[code] = course
        for title, status, confidence, ago in topics:
            t = store.add_topic(Topic(course.id, title, status, confidence,
                                      today - timedelta(days=ago) if ago is not None else None))
            topic_ids[(code, title)] = t.id
            if ago is not None and ago < 7:
                started.add((code, title))

    for code, topic, text, priority, ago in WEAK:
        store.add_weak_spot(WeakSpot(courses[code].id, text, priority, topic_ids[(code, topic)],
                                     created_at=now - timedelta(days=ago)))

    from .logic.reading import parse_section_ranges

    for code, title, author, chapters in READING:
        source = store.add_source(Source(courses[code].id, title, author, **CITATIONS.get(title, {})))
        for number, chapter_title, topic, ranges, read_up_to, optional in chapters:
            numbers = parse_section_ranges(ranges, number)
            store.add_chapter(source.id, number, chapter_title, numbers, topic_ids[(code, topic)])
            listed = {sec.number: sec for _, chs in store.reading_list(courses[code].id) for _, ss in chs for sec in ss
                      if sec.number in numbers}
            store.set_required([listed[n].id for n in optional], False)
            read = [listed[n].id for n in numbers[:read_up_to] if n not in optional]
            # Ticked directly so the demo topics keep the statuses and study dates chosen above
            # (ticking through the store would count the reading as studying them today).
            for section_id in read:
                store.conn.execute("update section set read = 1, read_at = ? where id = ?",
                                   ((now - timedelta(days=2)).isoformat(timespec="minutes"), section_id))

    for code, title, kind, taken_on, score, questions in EXAMS:
        exam = store.add_exam(Exam(courses[code].id, title, kind, taken_on, score,
                                   notes="**Time:** 2 hours. **Aids:** none." if kind == "practice" else "",
                                   created_at=now - timedelta(days=12 if kind == "past" else 1)))
        store.replace_questions(exam.id, [ExamQuestion(exam.id, number, prompt, answer, marks, topic_ids[(code, topic)],
                                                       result, note, why)
                                          for number, topic, marks, result, note, prompt, answer, why in questions])

    for code, title, kind, hours, done in DEADLINES:
        due = (now + timedelta(hours=hours)).replace(minute=0)
        store.add_deadline(Deadline(title, due, kind, courses[code].id if code else None, done))

    # Two weeks of study sessions, heavier on the courses with exams coming up.
    pattern = [("DAT255", 90), ("INF301", 60), ("STK310", 45), ("INF301", 50), ("DAT255", 75), ("STK310", 30)]
    for day in range(14, -1, -1):
        d = today - timedelta(days=day)
        if d.weekday() == 5 and day > 6:  # a Saturday off
            continue
        for i, (code, minutes) in enumerate(pattern[day % 3: day % 3 + 2 + (day % 2)]):
            start = datetime.combine(d, time(9 + 3 * i, 15))
            if start > now:
                continue
            titles = sorted(t for (c, t) in started if c == code)
            topic = titles[(day + i) % len(titles)]
            store.log_session(Session(courses[code].id, start, minutes + (day % 4) * 5, topic_ids[(code, topic)]))


    seed_project(store, now)


def seed_project(store: Store, now: datetime) -> None:
    today = now.date()
    d = PROJECT
    p = store.add_project(Project(d["title"], d["description"], tags=d["tags"], start_on=today - timedelta(days=40),
                                  end_on=today + timedelta(days=120), color=store.next_color()))
    for title, body, ago in d["notes"]:
        note = store.add_note(ProjectNote(p.id, title, body, created_at=now - timedelta(days=ago + 2)))
        # As if last edited `ago` days back, in the sync column's UTC format.
        edited = (now - timedelta(days=ago)).astimezone().astimezone(timezone.utc)
        store.conn.execute("update project_note set updated_at = ? where id = ?",
                           (edited.strftime("%Y-%m-%dT%H:%M:%S.000Z"), note.id))
    for ago, body in d["entries"]:
        store.add_entry(ProjectEntry(p.id, today - timedelta(days=ago), body))
    for name, url, category in d["links"]:
        store.add_link(ProjectLink(p.id, name, url, category))
    for title, authors, year, link, status, annotation in d["sources"]:
        store.add_project_source(ProjectSource(p.id, title, authors, year,
                                               f"https://doi.org/{link}" if link.startswith("10.") else link,
                                               status, annotation))
    for text, done in d["tasks"]:
        task = store.add_task(ProjectTask(p.id, text))
        if done:
            store.toggle_task(task.id, now - timedelta(days=2))
    for day, minutes in ((6, 80), (5, 45), (3, 60), (2, 90), (1, 40), (0, 35)):
        start = datetime.combine(today - timedelta(days=day), time(16, 30))
        if start <= now:
            store.log_session(Session(None, start, minutes, note="Experiments", project_id=p.id))


def temporary_store_path() -> Path:
    """A fresh database in a temp folder that's removed when the program exits."""
    folder = Path(tempfile.mkdtemp(prefix="studypal-demo-"))
    atexit.register(shutil.rmtree, folder, True)
    path = folder / "study.db"
    os.environ["STUDYPAL_DB"] = str(path)
    return path
