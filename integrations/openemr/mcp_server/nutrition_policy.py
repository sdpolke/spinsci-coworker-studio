"""Nutrition clinic scheduling rules, transcribed from the workflow spec.

Every constant here traces back to a ``detailLines`` entry in
``docs/json_workflows_samples/nutrition_agent_workflow.json``. Keeping the
rules in one I/O-free module means the MCP tools stay thin (fetch from OpenEMR,
apply a rule, return) and the rules themselves can be exercised directly.

Intentionally no OpenEMR imports: this module must stay pure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# --- age routing -----------------------------------------------------------
# "Route every pediatric patient to Alexa Bacino."
PEDIATRIC_AGE_LIMIT = 18
PEDIATRIC_PROVIDER = "Alexa Bacino"

# --- condition eligibility -------------------------------------------------
# "Approve Diabetes, Pre-diabetes, GDM, Weight Management, Gastroenterology,
#  Bariatric, Hyperlipidemia, Celiac, Gluten Intolerance, Obesity, and General
#  Nutrition."
APPROVED_CONDITIONS: dict[str, tuple[str, ...]] = {
    "Diabetes": ("diabetes", "dm", "t1dm", "t2dm"),
    "Pre-diabetes": ("pre-diabetes", "prediabetes", "pre diabetes"),
    "Gestational Diabetes": ("gestational diabetes", "gdm"),
    "Weight Management": ("weight management", "weight loss"),
    "Gastroenterology": ("gastroenterology", "gastro", "ibs", "crohn", "colitis"),
    "Bariatric": ("bariatric", "gastric bypass", "sleeve"),
    "Hyperlipidemia": ("hyperlipidemia", "high cholesterol", "dyslipidemia"),
    "Celiac": ("celiac",),
    "Gluten Intolerance": ("gluten intolerance", "gluten sensitivity"),
    "Obesity": ("obesity", "obese"),
    "General Nutrition": ("general nutrition", "nutrition counseling"),
}

# "Do not schedule Eating Disorders, Adult Tube Feedings, or Nephrology."
REFER_OUT_CONDITIONS: dict[str, tuple[str, ...]] = {
    "Eating Disorder": ("eating disorder", "anorexia", "bulimia", "arfid"),
    "Adult Tube Feeding": ("tube feeding", "enteral", "peg tube"),
    "Nephrology": ("nephrology", "renal", "kidney disease", "dialysis"),
}

REFER_OUT_DESTINATIONS = {
    "Eating Disorder": "the eating disorder program",
    "Adult Tube Feeding": "the clinical nutrition support team",
    "Nephrology": "the renal nutrition team",
}

# --- GDM rules -------------------------------------------------------------
# "Verify that the referral came from a Summit Health provider."
GDM_REQUIRED_REFERRAL_ORG = "Summit Health"
# "GDM must be scheduled within 72 hours."
GDM_SCHEDULING_WINDOW_HOURS = 72
# "No GDM slot is available within 72 hours. Call 908-516-9850 and select option 2."
GDM_ESCALATION_PHONE = "908-516-9850"
GDM_ESCALATION_OPTION = "2"

# --- slot / visit-type policy ---------------------------------------------
# "Allow virtual visits only in Athena Telehealth slots. Never change a preset
#  slot to Virtual, OV, or NEWP."
TELEHEALTH_VISIT_TYPE = "Nutrition Telehealth"
IN_PERSON_VISIT_TYPES = ("Nutrition New Patient", "Nutrition Follow Up")
PROTECTED_VISIT_TYPES = ("Nutrition Telehealth", "Nutrition New Patient", "Nutrition Follow Up")

# --- coverage --------------------------------------------------------------
# "State that there is a $200 charge if the diagnosis is not covered by insurance."
SELF_PAY_FEE_USD = 200

# --- clinic hours ----------------------------------------------------------
CLINIC_OPEN = time(9, 0)
CLINIC_CLOSE = time(16, 30)
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 0)
SLOT_GRANULARITY_MINUTES = 30

# --- patient instructions --------------------------------------------------
# "Tell new patients to bring their most recent laboratory results. Tell
#  patients who test at home to bring their blood sugar logbook."
NEW_PATIENT_INSTRUCTION = (
    "Please bring your most recent laboratory results to the visit."
)
GLUCOSE_LOG_INSTRUCTION = (
    "If you test your blood sugar at home, please bring your blood sugar logbook."
)


def calculate_age(dob: str | date, *, on: date | None = None) -> int | None:
    """Age in whole years, or None when the date of birth is unusable."""
    if isinstance(dob, date):
        birth = dob
    else:
        if not dob:
            return None
        try:
            birth = datetime.strptime(str(dob)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    today = on or date.today()
    return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))


def is_pediatric(age: int | None) -> bool:
    """Unknown age is treated as adult; the age gate asks rather than guesses."""
    return age is not None and age < PEDIATRIC_AGE_LIMIT


@dataclass(frozen=True)
class ConditionDecision:
    """Outcome of screening a problem list against the nutrition criteria."""

    status: str  # "approved" | "refer_out" | "unknown"
    category: str | None
    matched_text: str | None
    is_gdm: bool
    refer_to: str | None

    @property
    def approved(self) -> bool:
        return self.status == "approved"


def _match(text: str, table: dict[str, tuple[str, ...]]) -> tuple[str, str] | None:
    """Match against the most specific keyword, not the first one declared.

    Categories overlap by design: "Gestational Diabetes Mellitus" contains both
    "gestational diabetes" and "diabetes". Matching the longest keyword keeps
    GDM out of the generic Diabetes bucket, which matters because GDM carries
    its own referral and 72-hour scheduling rules.
    """
    lowered = text.lower()
    best: tuple[int, str] | None = None
    for category, keywords in table.items():
        for keyword in keywords:
            if keyword in lowered and (best is None or len(keyword) > best[0]):
                best = (len(keyword), category)
    return (best[1], text) if best else None


def classify_conditions(problem_titles: list[str]) -> ConditionDecision:
    """Screen a problem list. Refer-out wins over approval.

    A patient carrying both an approved condition and a refer-out condition
    must not be booked, so refer-out is evaluated first.
    """
    for title in problem_titles:
        hit = _match(title or "", REFER_OUT_CONDITIONS)
        if hit:
            category, matched = hit
            return ConditionDecision(
                status="refer_out",
                category=category,
                matched_text=matched,
                is_gdm=False,
                refer_to=REFER_OUT_DESTINATIONS.get(category),
            )

    for title in problem_titles:
        hit = _match(title or "", APPROVED_CONDITIONS)
        if hit:
            category, matched = hit
            return ConditionDecision(
                status="approved",
                category=category,
                matched_text=matched,
                is_gdm=category == "Gestational Diabetes",
                refer_to=None,
            )

    return ConditionDecision(
        status="unknown",
        category=None,
        matched_text=None,
        is_gdm=False,
        refer_to=None,
    )


def referral_is_internal(referrer: str | None) -> bool:
    """True when the referral came from a Summit Health provider."""
    return bool(referrer) and GDM_REQUIRED_REFERRAL_ORG.lower() in referrer.lower()


def gdm_deadline(now: datetime | None = None) -> datetime:
    return (now or datetime.now()) + timedelta(hours=GDM_SCHEDULING_WINDOW_HOURS)


def validate_visit_type(
    slot_visit_type: str, *, wants_virtual: bool
) -> tuple[bool, str]:
    """Check a requested slot against the visit-type policy.

    Returns ``(allowed, reason)``. Reason is phrased for the agent to speak.
    """
    if wants_virtual and slot_visit_type != TELEHEALTH_VISIT_TYPE:
        return False, (
            f"A virtual visit can only be booked in a {TELEHEALTH_VISIT_TYPE} slot. "
            f"This slot is {slot_visit_type}, and its type cannot be changed."
        )
    if not wants_virtual and slot_visit_type == TELEHEALTH_VISIT_TYPE:
        return False, (
            f"This is a {TELEHEALTH_VISIT_TYPE} slot and is only for virtual visits. "
            "Its type cannot be changed to an in-person visit."
        )
    return True, f"{slot_visit_type} is valid for this request."


def instructions_for(*, is_new_patient: bool, tests_at_home: bool) -> list[str]:
    out: list[str] = []
    if is_new_patient:
        out.append(NEW_PATIENT_INSTRUCTION)
    if tests_at_home:
        out.append(GLUCOSE_LOG_INSTRUCTION)
    return out


def candidate_slot_starts(day: date) -> list[time]:
    """Bookable start times on a weekday, excluding the lunch hour."""
    if day.weekday() >= 5:
        return []

    out: list[time] = []
    cursor = datetime.combine(day, CLINIC_OPEN)
    closing = datetime.combine(day, CLINIC_CLOSE)
    while cursor < closing:
        moment = cursor.time()
        if not (LUNCH_START <= moment < LUNCH_END):
            out.append(moment)
        cursor += timedelta(minutes=SLOT_GRANULARITY_MINUTES)
    return out
