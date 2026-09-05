"""Zone Contention Solver - Tree-of-Thoughts + beam search.

Picks one irrigation run duration for a **heterogeneous** zone (e.g. Mango with
low over-water tolerance sharing a zone with Jaboticaba which drinks heavily).
Pure, synchronous, deterministic - it is a LangGraph node and has no model / DB.

    1. thought generation : candidate durations {10,20,30,40,50} min + split/pulsed runs
    2. cost evaluation    : simulate post-irrigation VWC per species; exponential
                            saturation / drought penalties
    3. beam search        : keep the top k=2, vary +/-3 min, re-score, pick the winner
                            (ties -> the shorter run, to save water)

``estimated_gph`` is the whole-tree drip delivery rate:
    Volume_gal = (D / 60) * estimated_gph
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..irrigation.water_score import credited_forecast_mm

from ..core.tracing import traced

GAL_TO_L: float = 3.78541
_ROOT_DEPTH_M = 0.30            # effective root-zone depth for VWC bookkeeping
_MIN_WETTED_AREA_M2 = 0.5
_DEFAULT_SPREAD_M = 2.5
_DEFAULT_GPH = 8.0             # whole-tree drip delivery (gal/hour) when unknown
_WETTED_CANOPY_FRACTION = 0.30  # drip wets ~a third of the canopy footprint (fallback only)


# -- per-species hydraulic comfort bands -------------------------------

@dataclass(frozen=True)
class SpeciesWaterProfile:
    sat_vwc: float               # above this -> root-saturation risk
    wilt_vwc: float              # below this -> drought risk
    et_mm_day: float             # rough daily crop evapotranspiration
    k_sat: float = 0.35          # saturation-penalty steepness
    k_wilt: float = 0.35         # drought-penalty steepness


_PROFILES: dict[str, SpeciesWaterProfile] = {
    # Mango: shallow, hates wet feet -> low sat_vwc, steep saturation penalty
    "mango": SpeciesWaterProfile(sat_vwc=31.0, wilt_vwc=13.0, et_mm_day=4.5, k_sat=0.60),
    # Jaboticaba: high, constant water demand -> high wilt_vwc, steep drought penalty
    "jaboticaba": SpeciesWaterProfile(sat_vwc=44.0, wilt_vwc=23.0, et_mm_day=5.5, k_wilt=0.60),
    "jabuticaba": SpeciesWaterProfile(sat_vwc=44.0, wilt_vwc=23.0, et_mm_day=5.5, k_wilt=0.60),
    "avocado": SpeciesWaterProfile(sat_vwc=33.0, wilt_vwc=16.0, et_mm_day=4.0, k_sat=0.50),
    "citrus": SpeciesWaterProfile(sat_vwc=36.0, wilt_vwc=15.0, et_mm_day=3.5),
    "lychee": SpeciesWaterProfile(sat_vwc=40.0, wilt_vwc=20.0, et_mm_day=5.0, k_wilt=0.45),
    "banana": SpeciesWaterProfile(sat_vwc=46.0, wilt_vwc=24.0, et_mm_day=6.0, k_wilt=0.55),
}
_GENERIC = SpeciesWaterProfile(sat_vwc=36.0, wilt_vwc=15.0, et_mm_day=4.0)


def profile_for(species: str) -> SpeciesWaterProfile:
    s = (species or "").lower()
    for keyword, profile in _PROFILES.items():
        if keyword in s:
            return profile
    return _GENERIC


# -- inputs / outputs ------------------------------------------------

@dataclass(frozen=True)
class TreeHydro:
    tree_id: int
    species: str
    current_vwc: float | None
    canopy_spread_m: float | None
    estimated_gph: float | None            # whole-tree drip delivery, gal/hour
    wetted_area_m2: float | None           # grower estimate of soil area the emitters wet
    target_vwc: float | None = None        # phenology-derived target (app.irrigation.phenology);
                                            # optional - no sensor / unknown species leaves it unset

    @property
    def _spread(self) -> float:
        return float(self.canopy_spread_m) if self.canopy_spread_m else _DEFAULT_SPREAD_M

    @property
    def _gph(self) -> float:
        return float(self.estimated_gph) if self.estimated_gph else _DEFAULT_GPH


@dataclass(frozen=True)
class Candidate:
    minutes: int
    pulses: int = 1              # >1 = split/pulsed run (better infiltration)

    def label(self) -> str:
        return f"{self.minutes} min" + (f" x{self.pulses} pulses" if self.pulses > 1 else "")


@dataclass(frozen=True)
class TreeOutcome:
    tree_id: int
    species: str
    delivered_gal: float
    post_vwc: float
    penalty: float


@dataclass(frozen=True)
class CandidateEval:
    candidate: Candidate
    total_penalty: float
    outcomes: list[TreeOutcome]


@dataclass(frozen=True)
class ZoneSolution:
    recommended_minutes: int
    pulses: int
    baseline_minutes: int
    delta_minutes: int                     # recommended - baseline
    total_penalty: float
    per_tree: list[TreeOutcome]
    candidates_considered: int
    rationale: str
    thoughts: list[dict] = field(default_factory=list)   # beam trace, for the summary / UI

    @property
    def is_change(self) -> bool:
        return self.delta_minutes != 0


# -- water math ----------------------------------------------------

def delivered_gallons(tree: TreeHydro, minutes: float) -> float:
    return (minutes / 60.0) * tree._gph


def _wetted_area_m2(tree: TreeHydro) -> float:
    """Soil the drip emitters actually wet - NOT the whole canopy. The grower's
    own estimate when given, otherwise a fraction of the canopy footprint."""
    if tree.wetted_area_m2:
        return max(float(tree.wetted_area_m2), _MIN_WETTED_AREA_M2)
    canopy = math.pi * (tree._spread / 2.0) ** 2
    return max(_WETTED_CANOPY_FRACTION * canopy, _MIN_WETTED_AREA_M2)


def _delta_vwc(depth_mm: float) -> float:
    """A mm of water over the wetted zone -> VWC percentage points."""
    return depth_mm / (_ROOT_DEPTH_M * 1000.0) * 100.0


def simulate_post_vwc(
    tree: TreeHydro,
    candidate: Candidate,
    *,
    rain_24h_mm: float,
    forecast_rain_24h_mm: float,
) -> float:
    """Root-zone VWC after this run + rain, minus a day of ET. Bounded 0..60%."""
    prof = profile_for(tree.species)
    area = _wetted_area_m2(tree)

    irrig_mm = delivered_gallons(tree, candidate.minutes) * GAL_TO_L / area  # L/m2 == mm
    d_irrig = _delta_vwc(irrig_mm)
    if candidate.pulses > 1:
        # pulsed delivery infiltrates rather than ponding -> smaller effective spike
        d_irrig *= 1.0 - 0.10 * min(candidate.pulses - 1, 3)

    d_rain = _delta_vwc(rain_24h_mm + credited_forecast_mm(forecast_rain_24h_mm))
    et_vwc = _delta_vwc(prof.et_mm_day)

    start = (
        tree.current_vwc
        if tree.current_vwc is not None
        else (prof.wilt_vwc + prof.sat_vwc) / 2.0
    )
    return max(0.0, min(60.0, start + d_irrig + d_rain - et_vwc))


_SOFT_MARGIN = 5.0   # VWC points before a hard threshold where the penalty starts rising

# Weight for the phenology-target-tracking term in penalty(). Deliberately
# small relative to the exponential wilt/saturation guards above - a gap of a
# few VWC points past the soft margin already outscores anything this term can
# produce, so the guards keep governing behaviour near the hard thresholds.
# But inside the flat interior (both guards exactly 0, which is where the old
# objective was blind) it is the *only* signal, so it has to be big enough to
# separate candidates a coarse/fine grid step apart. 0.08 does that: two
# candidates 10 minutes apart typically land several VWC points apart, which
# clears the 0.01 resolution the winner rule rounds penalties to
# (round(total_penalty, 2)); a species band's full width (5-20 VWC points)
# only costs 0.4-1.6, well under a guard's climb over the same range. Tune
# against the eval before nudging - this is a starting value, not a derived one.
_TARGET_TRACKING_WEIGHT = 0.08

# Deadband (VWC points) around the clamped target inside which the tracking
# term costs nothing. Clamping alone (see clamp_target_vwc) is not sufficient
# when the *clamped* target is itself unreachable within the grid ceiling
# (53 min): the tracking term keeps falling monotonically as duration climbs
# toward the ceiling because the flat interior never actually reaches the
# target, so a *mild* deficit still proposed the grid-ceiling run - measured
# on irr-04 (a 6-point deficit inside the tolerance band): clamp-only still
# produced 53 min (eval run 2026-09-03T18:11Z, orchard-server/eval/results/
# 20260903T181124Z.json). This deadband stops that chase once the post-run
# VWC is "close enough": the existing fewest-minutes tie-break then picks the
# driest candidate in the now-flat zero-penalty region (the owner's "on any
# tie, prefer less water" rule). 3.5 was chosen by sweeping 1.0-5.0 against
# the eval's irrigation channel: it brings irr-04 down to a 27 min / +2 min
# adjustment (was 53 / +28) while a genuinely large, grid-reachable gap still
# gets watered most of the way there (an 8-point gap synthetic case moved
# from a 0-point undershoot at deadband=0 to a 3.5-point undershoot - i.e. it
# stops exactly at the deadband edge, not before). Severe-deficit rows
# (irr-05, irr-07 - the drought *guard*, not this term, is what drives them)
# are untouched at every deadband tested up to 5.0: they stay at the 53 min
# grid ceiling because the guard difference between candidates dwarfs any
# tracking delta this deadband could hide. A deadband much larger than this
# (5.0 was tested) starts neutering genuine tracking on reachable gaps too -
# a 20-min-short case rounds all the way down to baseline - so this is a
# floor, not a free parameter to raise further without re-running the sweep.
_TARGET_DEADBAND_VWC = 3.5


def clamp_target_vwc(species: str, target_vwc: float) -> float:
    """Pull a phenology ``target_vwc`` back inside the species' comfort band
    ``[wilt_vwc + _SOFT_MARGIN, sat_vwc - _SOFT_MARGIN]`` before it can enter
    the objective.

    Owner decision: underwatering is preferred over overwatering. Without
    this, a growth-stage target that sits past a species' own saturation
    guard (mango's ``fruit_development`` target is 27% VWC, but its guard
    starts biting at ``sat_vwc - _SOFT_MARGIN`` = 26%) pulls the objective
    toward a point the guard is built to punish - penalty keeps *falling* as
    duration climbs toward the grid ceiling because the flat interior never
    reaches the (unreachable) target. Clamping means the guard wins on any
    target/guard conflict, and the tracking term never fights the guard it
    shares a species profile with.
    """
    prof = profile_for(species)
    band_lo = prof.wilt_vwc + _SOFT_MARGIN
    band_hi = prof.sat_vwc - _SOFT_MARGIN
    if band_lo > band_hi:  # pathologically narrow profile - collapse to the midpoint
        return (band_lo + band_hi) / 2.0
    return min(max(target_vwc, band_lo), band_hi)


def penalty(species: str, post_vwc: float, target_vwc: float | None = None) -> float:
    """Exponential drought / saturation penalty, plus - when a phenology
    ``target_vwc`` is known - a small linear pull toward it (clamped into the
    species' comfort band first, see :func:`clamp_target_vwc`, then given a
    ``_TARGET_DEADBAND_VWC`` no-cost zone around it). Near-zero while the
    tree sits comfortably in its band *and* close to target; climbs steeply
    as it nears (and passes) the species' wilt or saturation threshold, where
    the guard terms take back over regardless of target."""
    prof = profile_for(species)
    drought_gap = (prof.wilt_vwc + _SOFT_MARGIN) - post_vwc
    saturation_gap = post_vwc - (prof.sat_vwc - _SOFT_MARGIN)
    drought = math.exp(prof.k_wilt * max(0.0, drought_gap)) - 1.0
    saturation = math.exp(prof.k_sat * max(0.0, saturation_gap)) - 1.0
    tracking = 0.0
    if target_vwc is not None:
        clamped = clamp_target_vwc(species, target_vwc)
        beyond_deadband = max(0.0, abs(post_vwc - clamped) - _TARGET_DEADBAND_VWC)
        tracking = _TARGET_TRACKING_WEIGHT * beyond_deadband
    return round(drought + saturation + tracking, 3)


def evaluate(
    trees: list[TreeHydro],
    candidate: Candidate,
    *,
    rain_24h_mm: float,
    forecast_rain_24h_mm: float,
) -> CandidateEval:
    outcomes: list[TreeOutcome] = []
    for t in trees:
        post = simulate_post_vwc(
            t, candidate, rain_24h_mm=rain_24h_mm, forecast_rain_24h_mm=forecast_rain_24h_mm
        )
        outcomes.append(
            TreeOutcome(
                tree_id=t.tree_id,
                species=t.species,
                delivered_gal=round(delivered_gallons(t, candidate.minutes), 1),
                post_vwc=round(post, 1),
                penalty=penalty(t.species, post, t.target_vwc),
            )
        )
    return CandidateEval(candidate, round(sum(o.penalty for o in outcomes), 3), outcomes)


# -- the solver --------------------------------------------------

_COARSE_MINUTES = (10, 20, 30, 40, 50)
_PULSED = (Candidate(20, 2), Candidate(30, 2), Candidate(40, 3))
_BEAM_K = 2
_FINE_DELTAS = (-3, 0, 3)


@traced("irrigation.tot_solver")
def solve(
    trees: list[TreeHydro],
    *,
    baseline_minutes: int,
    rain_24h_mm: float = 0.0,
    forecast_rain_24h_mm: float = 0.0,
) -> ZoneSolution:
    if not trees:
        return ZoneSolution(
            recommended_minutes=baseline_minutes,
            pulses=1,
            baseline_minutes=baseline_minutes,
            delta_minutes=0,
            total_penalty=0.0,
            per_tree=[],
            candidates_considered=0,
            rationale="No trees mapped to this zone - keeping the baseline.",
        )

    kw = {"rain_24h_mm": rain_24h_mm, "forecast_rain_24h_mm": forecast_rain_24h_mm}

    coarse = [Candidate(m) for m in _COARSE_MINUTES] + list(_PULSED)
    evals = sorted((evaluate(trees, c, **kw) for c in coarse), key=lambda e: e.total_penalty)
    beam = evals[:_BEAM_K]

    fine: list[CandidateEval] = []
    seen: set[tuple[int, int]] = set()
    for e in beam:
        for dm in _FINE_DELTAS:
            m = max(0, e.candidate.minutes + dm)
            key = (m, e.candidate.pulses)
            if key in seen:
                continue
            seen.add(key)
            fine.append(evaluate(trees, Candidate(m, e.candidate.pulses), **kw))

    # winner: lowest penalty, then fewest minutes (save water on a tie)
    pool = beam + fine
    winner = min(pool, key=lambda e: (round(e.total_penalty, 2), e.candidate.minutes))

    delta = winner.candidate.minutes - baseline_minutes
    thoughts = [
        {"candidate": e.candidate.label(), "penalty": e.total_penalty}
        for e in sorted(pool, key=lambda e: e.total_penalty)[:5]
    ]
    return ZoneSolution(
        recommended_minutes=winner.candidate.minutes,
        pulses=winner.candidate.pulses,
        baseline_minutes=baseline_minutes,
        delta_minutes=delta,
        total_penalty=round(winner.total_penalty, 2),
        per_tree=winner.outcomes,
        candidates_considered=len(coarse) + len(fine),
        rationale=_rationale(winner, baseline_minutes, delta),
        thoughts=thoughts,
    )


def _rationale(winner: CandidateEval, baseline: int, delta: int) -> str:
    band = "; ".join(
        f"{o.species} -> {o.post_vwc}% VWC" for o in winner.outcomes
    )
    if delta < 0:
        move = f"reduce the run from {baseline} to {winner.candidate.minutes} min (saves {-delta} min)"
    elif delta > 0:
        move = f"raise the run from {baseline} to {winner.candidate.minutes} min"
    else:
        move = f"keep the {baseline} min run"
    pulse = " as a pulsed run" if winner.candidate.pulses > 1 else ""
    return f"{winner.candidate.label()}{pulse}: {move} - projected {band}."
