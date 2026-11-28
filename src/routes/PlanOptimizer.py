"""Builds the study plan as an optimization problem (Operations Research, MILP).

The LLM only reads the student's note. Here we decide the hours:

1. DEMAND   how much time each subject deserves (its weight):
              focus x size of the material x weakness in its quizzes
2. TARGETS  every subject first gets a fair floor, then the rest of the hours are shared
              by weight, never more than a subject can use before its exam
3. SOLVE    a MILP picks how many half-hours of each subject go on each day so that
              the plan is as close as possible to the targets while the rules hold.

Hard rules (the same ones PlanScheduler has):
- a day never goes over the student's hours
- nothing is planned on rest days, before the start day, or for a subject on/after its exam day
- max subjects per day, when the student asked for it
Soft rules (the solver pays a cost to break them, so a plan always exists):
- every subject is studied on the last usable day before its exam
- each subject is spread over its days at an even pace, so days are mixed and not
  "all Math first, then all Physics"

Anything wrong (no solution, a result that fails our own check) raises OptimizerError,
and the caller falls back to PlanScheduler.build_plan.
"""
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from controllers.PlanScheduler import FOCUS_WEIGHT, ScheduleResult, _day_blocks, _targets
from models.PlannerOutput import ExamItem
from models.enums.PlannerEnums import Weekday

EPS = 1e-6

# --- demand ---------------------------------------------------------------
SIZE_MIN, SIZE_MAX = 0.7, 1.5  # a subject's size counts between 0.7x and 1.5x the average
WEAK_MIN, WEAK_MAX = 0.7, 1.3  # weakness factor: strong subject 0.7x, failing subject 1.3x
FLOOR_SHARE = 0.6  # every subject gets at least 60% of an equal share of the hours
NEUTRAL_ACCURACY = 0.5  # used when the student has no quiz in that subject yet

# --- objective (cost per half-hour unless said otherwise) --------------------
COST_SHORT = 10.0  # a half-hour less than the subject's target
COST_EXTRA = 3.0  # a half-hour more than the target
COST_NO_LAST_DAY = 50.0  # the subject is not studied on its last usable day
COST_PACE = 1.0  # a half-hour away from the subject's even daily pace

SOLVER_TIME_LIMIT = 10.0  # seconds
MIP_GAP = 1e-2  # stop when the plan is within 1% of the best possible


class OptimizerError(Exception):
    """The optimizer could not produce a trustworthy plan."""


def demand_weights(
    exams: list[ExamItem], stats: dict | None, focus_subjects: list[str]
) -> list[float]:
    """One weight per exam: the bigger the weight, the more study time the subject gets.

    weight = focus (1.5 if the student asked) x size factor x weakness factor
    - size factor: material size vs the average of the exam subjects, kept between 0.7 and 1.5
    - weakness factor: 0.7 (all answers right) to 1.3 (all wrong), 1.0 if no quiz yet
    An exam with no card or no stats gets 1.0 for both, so it is planned as before.
    """
    stats = stats or {}
    focus = {name.lower() for name in focus_subjects}

    sizes = [
        stats[e.card_id]["chars"]
        for e in exams
        if e.card_id in stats and stats[e.card_id].get("chars", 0) > 0
    ]
    mean_size = sum(sizes) / len(sizes) if sizes else 0.0

    weights = []
    for exam in exams:
        info = stats.get(exam.card_id) or {}

        chars = info.get("chars", 0)
        size_factor = 1.0
        if mean_size > 0 and chars > 0:
            size_factor = min(SIZE_MAX, max(SIZE_MIN, chars / mean_size))

        accuracy = info.get("accuracy")
        if accuracy is None:
            accuracy = NEUTRAL_ACCURACY
        weak_factor = WEAK_MIN + (WEAK_MAX - WEAK_MIN) * (1.0 - min(1.0, max(0.0, accuracy)))

        focus_factor = FOCUS_WEIGHT if exam.subject.lower() in focus else 1.0
        weights.append(focus_factor * size_factor * weak_factor)
    return weights


def _share_hours(weight: dict, cap: dict, total: float) -> dict:
    """Targets in half-hours: a floor for everyone, then the rest by weight (never above cap)."""
    base = {i: min(cap[i], FLOOR_SHARE * total / len(weight)) for i in weight}
    left = total - sum(base.values())
    room = {i: cap[i] - base[i] for i in weight}
    if left <= EPS or not any(r > EPS for r in room.values()):
        return base
    extra = _targets(weight, room, left)
    return {i: base[i] + extra.get(i, 0.0) for i in weight}


def optimize_plan(
    exams: list[ExamItem],
    hours_per_day: float,
    rest_weekdays: list[Weekday],
    focus_subjects: list[str],
    start: date,
    max_subjects_per_day: int | None = None,
    stats: dict | None = None,
    time_limit: float = SOLVER_TIME_LIMIT,
) -> ScheduleResult:
    rest = set(rest_weekdays)
    last_exam = max(e.exam_date for e in exams)
    max_subjects = max_subjects_per_day if max_subjects_per_day and max_subjects_per_day >= 1 else None

    # usable days: from start to the day before the last exam, no rest days
    days, day = [], start
    while day < last_exam:
        if Weekday.from_date(day) not in rest:
            days.append(day)
        day += timedelta(days=1)

    unit_cap = int(round(sum(_day_blocks(hours_per_day)) * 2))  # half-hours per day
    window = [[k for k, d in enumerate(days) if d < e.exam_date] for e in exams]
    reachable = [i for i in range(len(exams)) if window[i]]

    result = ScheduleResult(
        no_study_day=[exams[i].subject for i in range(len(exams)) if not window[i]]
    )
    if not reachable or unit_cap <= 0:
        return result

    # ---- demand -> targets (in half-hours) ------------------------------
    raw = demand_weights(exams, stats, focus_subjects)
    mean_w = sum(raw[i] for i in reachable) / len(reachable)
    weight = {i: raw[i] / mean_w for i in reachable}  # mean 1, so costs stay comparable
    cap = {i: float(len(window[i]) * unit_cap) for i in reachable}
    target = _share_hours(weight, cap, float(len(days) * unit_cap))
    pace = {i: target[i] / len(window[i]) for i in reachable}  # even half-hours per day

    # ---- variables -------------------------------------------------------
    col, lb, ub, integer, cost = {}, [], [], [], []

    def add(key, low, high, is_int, c):
        col[key] = len(cost)
        lb.append(low)
        ub.append(high)
        integer.append(1 if is_int else 0)
        cost.append(c)

    for i in reachable:
        for k in window[i]:
            add(("x", i, k), 0, unit_cap, True, 0.0)  # half-hours of subject i on day k
            if max_subjects is not None:  # "subject i is on day k" is needed only for the limit
                add(("y", i, k), 0, 1, True, 0.0)
            add(("dp", i, k), 0, np.inf, False, COST_PACE)  # above the even pace
            add(("dm", i, k), 0, np.inf, False, COST_PACE)  # below the even pace
        add(("pos", i), 0, np.inf, False, COST_EXTRA * weight[i])
        add(("neg", i), 0, np.inf, False, COST_SHORT * weight[i])
        add(("s", i), 0, 1, True, COST_NO_LAST_DAY)  # skipped its last usable day

    # ---- constraints -----------------------------------------------------
    rows, cols, vals, lo, hi = [], [], [], [], []

    def constrain(terms, low, high):
        r = len(lo)
        for c, v in terms:
            rows.append(r)
            cols.append(c)
            vals.append(v)
        lo.append(low)
        hi.append(high)

    by_day = defaultdict(list)
    for i in reachable:
        for k in window[i]:
            by_day[k].append(i)

    for k, subjects in by_day.items():
        constrain([(col[("x", i, k)], 1.0) for i in subjects], -np.inf, unit_cap)  # day capacity
        if max_subjects is not None:
            constrain([(col[("y", i, k)], 1.0) for i in subjects], -np.inf, max_subjects)

    for i in reachable:
        for k in window[i]:
            x = col[("x", i, k)]
            if max_subjects is not None:
                y = col[("y", i, k)]
                constrain([(x, 1.0), (y, -float(unit_cap))], -np.inf, 0.0)  # x > 0 needs y = 1
                constrain([(y, 1.0), (x, -1.0)], -np.inf, 0.0)  # y = 1 needs x >= 1
            constrain(  # x = even pace + above - below
                [(x, 1.0), (col[("dp", i, k)], -1.0), (col[("dm", i, k)], 1.0)], pace[i], pace[i]
            )

        # total hours = target + extra - short
        constrain(
            [(col[("x", i, k)], 1.0) for k in window[i]]
            + [(col[("pos", i)], -1.0), (col[("neg", i)], 1.0)],
            target[i],
            target[i],
        )
        # the last usable day before the exam gets at least one half-hour (or pay the cost)
        constrain([(col[("x", i, window[i][-1])], 1.0), (col[("s", i)], 1.0)], 1.0, np.inf)

    A = coo_matrix((vals, (rows, cols)), shape=(len(lo), len(cost))).tocsr()
    res = milp(
        c=np.array(cost),
        constraints=LinearConstraint(A, np.array(lo), np.array(hi)),
        integrality=np.array(integer),
        bounds=Bounds(np.array(lb), np.array(ub)),
        options={"time_limit": time_limit, "mip_rel_gap": MIP_GAP},
    )
    if res.x is None:
        raise OptimizerError(f"MILP found no solution: {res.message}")

    # ---- read the solution + check it ourselves --------------------------
    units = {  # (exam index, day index) -> half-hours
        (i, k): int(round(res.x[col[("x", i, k)]]))
        for i in reachable
        for k in window[i]
        if res.x[col[("x", i, k)]] > 0.5
    }
    _verify(units, days, exams, unit_cap, max_subjects)

    sessions_by_day, totals = defaultdict(dict), defaultdict(float)
    for (i, k), u in units.items():
        sessions_by_day[k][i] = u / 2
        totals[exams[i].subject] += u / 2

    for k in sorted(sessions_by_day):
        items = sorted(sessions_by_day[k].items(), key=lambda kv: (exams[kv[0]].exam_date, kv[0]))
        result.days.append(
            {
                "date": days[k].isoformat(),
                "sessions": [{"subject": exams[i].subject, "hours": h} for i, h in items],
            }
        )
    result.totals = dict(totals)
    studied = {i for (i, _k) in units}
    result.no_time = [exams[i].subject for i in reachable if i not in studied]
    return result


def _verify(units, days, exams, unit_cap, max_subjects) -> None:
    """Re-check the hard rules on the final answer. A wrong plan must never be returned."""
    per_day, subjects_on_day = defaultdict(int), defaultdict(set)
    for (i, k), u in units.items():
        if u <= 0:
            raise OptimizerError("non-positive session")
        if days[k] >= exams[i].exam_date:
            raise OptimizerError("a subject is planned on or after its exam day")
        per_day[k] += u
        subjects_on_day[k].add(i)
    if any(total > unit_cap for total in per_day.values()):
        raise OptimizerError("a day goes over the student's hours")
    if max_subjects is not None and any(len(s) > max_subjects for s in subjects_on_day.values()):
        raise OptimizerError("too many subjects in one day")