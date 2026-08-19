#!/usr/bin/env python3
"""R07 coverage lenses, and the routing that decides which guide reaches which lens.

WHY THIS FILE EXISTS — read before changing anything in it.

Igor asked (2026-08-18) that the guides in `AOS 2026/01-Руководства` be sent
along with the petition, calling them a "реестр законов". Two things were true
on inspection and both changed the design:

  1. They are NOT a registry of laws. They are derivative guides written inside
     this project family, and two of them self-label as unverified synthesis
     (LITIGATOR-ALGORITHM: "Это **мой синтез**", 🟡 across the file). Feeding an
     AI-authored guide to an adversarial AI lens and calling the agreement
     "verification" is circular — the same failure this project already recorded
     for quotation-checking. The guides carry 🟢/🟡 confidence markers, so the
     circularity is manageable, but ONLY if the lens is told about it. See
     GUIDE_PREAMBLE; it is not optional decoration.

  2. Reading them exposed that the twelve existing lenses have two holes, and
     the holes are where this filing is most exposed:

       * The cover letter spends its first ~800 words defending against
         8 CFR 103.2(a)(7)(iv) — the applicant is filing a SECOND I-485 while
         the first is still pending, and asking that they not be consolidated.
         Not one of the twelve lenses has jurisdiction over that. Three rounds,
         25 fatal findings, and the loudest argument in the document was never
         attacked, because no lens was allowed to.

       * Four of the seven guides (54% of that corpus) are about public charge
         under INA §212(a)(4). There is no public-charge lens at all.

     So the guides' real value is not "more context". It is a COVERAGE MAP: they
     show which questions the harness cannot currently ask.

Routing, not dumping. All seven guides on all fourteen lenses would be ~260K
tokens of mostly-irrelevant material per item, diluting the petition 3:1 and
invalidating the R04 canary result (measured at 89.7K, not at 354K). Each lens
gets only the guides that bear on it, and the twelve original lenses get NONE —
their corpus stays byte-identical to R06 so the regression grid stays readable.
"""
from __future__ import annotations

import pathlib

# --------------------------------------------------------------------------
# Guide provenance. This block is prepended to every guide bundle.
# --------------------------------------------------------------------------
GUIDE_PREAMBLE = """
═══ REFERENCE MATERIAL — READ THIS FRAMING FIRST ═══

What follows is NOT legal authority and NOT part of the petition record. It is a
set of working guides written by the applicant's own research process. Two of
them explicitly label themselves as unverified synthesis.

Treat them as A CHECKLIST OF ISSUES A REVIEWER SHOULD CONSIDER — nothing more.

Binding rules for your use of this material:
  * A finding must be grounded in the PETITION RECORD, or in a primary source
    (statute, regulation, published decision, USCIS Policy Manual) that the
    guide QUOTES and that you can see quoted. Never in the guide's own assertion.
  * Passages marked 🟡 are the author's unverified synthesis. You may use them to
    generate a QUESTION. You may never use them as an ANSWER.
  * Passages marked 🟢 claim to be verified against a primary source. Treat that
    claim as unconfirmed unless the quoted primary text is present.
  * If the guide and the petition record conflict, the RECORD governs and the
    conflict is itself worth reporting.
  * The guide agreeing with the petition is NOT evidence the petition is correct.
    Both may come from the same author. Say so if you catch yourself relying on it.

═══ END OF FRAMING ═══
"""

# --------------------------------------------------------------------------
# The two coverage lenses.
# --------------------------------------------------------------------------
EXTRA_LENSES: list[tuple[str, str]] = [
    ("duplicate-filing",
     "SECOND ADJUSTMENT APPLICATION FILED WHILE THE FIRST IS STILL PENDING.\n"
     "This is the single most unusual thing about this filing and it is the "
     "argument the cover letter leads with, so lead your attack there.\n\n"
     "The posture, whose particulars are in the record and are NOT restated here: "
     "an earlier Form I-485 remains pending on the basis of an already-approved "
     "I-140 in one employment-based classification, and the instant Form I-485 is "
     "filed on a NEW, concurrently filed I-140 in a DIFFERENT classification. The "
     "petitioner asks that the two NOT be consolidated and that the instant one be "
     "adjudicated on its own merits, arguing it is not a duplicate benefit request "
     "within 8 CFR 103.2(a)(7)(iv) because the two rest on different petitions, "
     "different statutory classifications and different eligibility analyses. "
     "Read the filing dates, receipt references and classifications OUT OF THE "
     "RECORD; do not assume any that is not there.\n\n"
     "Attack every leg of that, separately:\n"
     "(a) THE REGULATION. Does 8 CFR 103.2(a)(7)(iv) actually turn on the "
     "underlying petition, or on the BENEFIT REQUESTED? Both applications request "
     "the identical benefit — adjustment to LPR for the same beneficiary. Is "
     "'materially identical' measured by the relief sought or by the basis?\n"
     "(b) THE PROCEDURAL ASK. On what authority may an applicant DIRECT USCIS not "
     "to consolidate? What actually happens to #2 if #1 is approved first — and "
     "what happens to #1 if #2 is approved first? Is either rendered moot, "
     "abandoned, or denied, and does the petitioner's record show he has thought "
     "this through?\n"
     "(c) THE INFERENCE. An officer reading the instant application may infer the "
     "petitioner has lost confidence in the earlier basis. Is that inference "
     "available on this record, and does anything in the filing invite or rebut it?\n"
     "(d) THE §245 CARRY-OVER. If the record shows any adverse notice already "
     "issued on the earlier application under INA §245(c), note that the §245(c) "
     "analysis is a property of the APPLICANT's history, not of the underlying "
     "petition — so whatever is unresolved there transfers WHOLESALE to the "
     "instant one. Does the instant filing carry that burden, or proceed as if "
     "the question were new?\n"
     "(e) FEES, BIOMETRICS AND THE A-FILE. One A-file, two applications. What "
     "practical adjudication problems does that create, and has the filing "
     "anticipated them?\n\n"
     "For each: is there a LAWFUL cure — a better framing, a withdrawal, a "
     "sequencing choice, an explanatory statement? Never concealment."),

    ("public-charge",
     "PUBLIC CHARGE INADMISSIBILITY under INA §212(a)(4), and the discretionary "
     "weight it carries at adjustment. This is an I-485 ground that exists "
     "INDEPENDENTLY of anything in the I-140, and a NIW approval does not touch "
     "it.\n\n"
     "Work the totality-of-the-circumstances factors the statute enumerates — age; "
     "health; family status; assets, resources and financial status; education and "
     "skills — and for each, state what THIS record actually shows versus what it "
     "merely asserts.\n\n"
     "Then attack these specifically:\n"
     "(a) THE AFFIDAVIT OF SUPPORT QUESTION. For an employment-based SELF-petition "
     "with no relative petitioner, is Form I-864 required at all, and if not, is "
     "Form I-864W or nothing the correct posture? Does the record take a position, "
     "and is that position correct? A filing that is silent on a required form is "
     "as defective as one that files the wrong form.\n"
     "(b) INCOME AND SELF-SUFFICIENCY. What does the record actually evidence about "
     "the applicant's income, assets and prospective earnings — as opposed to "
     "narrating them? An unpaid or nominally-paid nonprofit officer role and a "
     "pre-revenue venture are the weakest possible showing on this factor.\n"
     "(c) PUBLIC BENEFITS. Does anything in the record disclose or imply receipt of "
     "any benefit within the definition? Silence is not the same as a negative, and "
     "an officer may ask.\n"
     "(d) HEALTH AND THE MEDICAL EXAM. Is Form I-693 addressed, current, and sealed?\n"
     "(e) THE INTERACTION WITH DISCRETION. Public charge and the PM-602-0199 "
     "discretionary analysis are separate tests that draw on overlapping facts. "
     "Where does a fact that is merely neutral for §212(a)(4) become NEGATIVE in "
     "discretion, or the reverse?\n\n"
     "Give the lawful cure for each: which document, signed by whom, saying what."),

    # ----------------------------------------------------------------------
    # Added 2026-08-18 AFTER the cheap panel. Q4 asked ten reviewers to name a
    # coverage hole none of the then-14 lenses could reach. Four converged on the
    # cross-application cascade and two on visa availability, independently.
    #
    # 🔴 The lenses below ask the reviewers' QUESTION. They deliberately do NOT
    # carry the reviewers' ANSWERS. One panel channel supported its version with
    # a regulation quote that does not read like the real text and a BIA case
    # about asylum that it admitted was "not directly on point". A panel tells
    # you where to look; it does not tell you what is there. Nothing below
    # asserts what any provision says — each asks what it says.
    # ----------------------------------------------------------------------
    ("cross-application-cascade",
     "DEPENDENCY BETWEEN THE TWO ADJUSTMENT APPLICATIONS. The petition treats "
     "I-485 #1 and I-485 #2 as independent. Test that assumption — it is the "
     "load-bearing premise of the whole filing strategy and it is asserted, not "
     "argued.\n\n"
     "Take the filing dates, the classifications and any adverse notice already "
     "issued FROM THE RECORD — they are there and are not restated here. Work the "
     "branches an officer would work:\n\n"
     "(a) IF THE EARLIER APPLICATION IS DENIED FIRST — what does the applicant's status and "
     "authorised-stay position become on the day of that denial? Does any "
     "employment authorisation that flows from #1 survive it? If it does not, "
     "what happens to work performed after that date while #2 is pending, and "
     "does the record show the applicant has planned for it?\n"
     "(b) THE §245(k) MEASURING DATE. §245(k) forgives a bounded period of "
     "violation measured from a particular event. For the LATER application, is "
     "that period measured from the same starting point the record uses for the "
     "EARLIER one — and does the answer still leave the applicant inside the "
     "allowance? This is the crux: an application asserted to be independent may "
     "not borrow the earlier application's measuring date. State what the record "
     "actually establishes about the status history and where it is silent.\n"
     "(c) AUTHORISED STAY IS NOT LAWFUL STATUS. A pending adjustment application "
     "confers one; whether it confers the other is a distinct question. Does the "
     "record rely anywhere on #1's pendency to establish something about #2 that "
     "pendency alone cannot establish?\n"
     "(d) ADMISSIBILITY CONTAMINATION. Is there any way a denial or an adverse "
     "finding on #1 makes the applicant inadmissible for #2 — as opposed to "
     "merely unsuccessful on #1? If so, name the mechanism and say whether the "
     "record addresses it.\n"
     "(e) THE UNANSWERED NOTICE. Whatever USCIS found troubling on the earlier "
     "application is a fact about the APPLICANT, not about the petition that "
     "application rested on. Does the instant filing carry that burden forward and "
     "answer it, or proceed as if it were new?\n\n"
     "Where you are unsure what a provision requires, SAY SO and frame it as the "
     "question an officer would ask — do not invent the provision's content. For "
     "each branch give the lawful cure: what evidence, sequencing or explanation."),

    ("visa-availability",
     "IMMEDIATE VISA AVAILABILITY AND THE PRIORITY DATE. An adjustment "
     "application has a filing gate that is prior to every merits question in "
     "this record, and nothing in the petition appears to address it.\n\n"
     "(a) THE GATE ITSELF. Adjustment under INA §245(a) requires that an "
     "immigrant visa be immediately available. State what that requires as of the "
     "filing date of I-485 #2, and identify what in THIS record establishes it. "
     "If nothing does, that is the finding.\n"
     "(b) THE TWO CATEGORIES ARE NOT ONE. The already-approved petition and the "
     "new petition sit in DIFFERENT employment-based preference categories, whose "
     "cut-off dates move independently. A category that is current for one is not "
     "thereby current for the other. Does the record show awareness of this, and "
     "does it evidence availability for the category the INSTANT filing rests on?\n"
     "(c) PRIORITY DATE RETENTION. If the applicant intends the earlier priority "
     "date to attach to the new petition, what must be done to claim it, and does "
     "the record show it was done — or is retention simply assumed? Assumed "
     "retention that fails at intake is a rejection, not an RFE.\n"
     "(d) CONCURRENT FILING. Filing I-485 together with a not-yet-approved I-140 "
     "depends on the category being open at that moment. If it is not, what "
     "happens to the instant I-485 — and is that outcome a rejection the "
     "applicant can cure, or a denial he cannot?\n\n"
     "🔴 You are NOT being asked to state the current Visa Bulletin — you do not "
     "have it and must not invent it. You are being asked whether THIS RECORD "
     "establishes the gate is satisfied, and what an officer would demand if it "
     "does not. An answer that asserts a specific cut-off date is a wrong answer."),
]

# --------------------------------------------------------------------------
# Routing. lens id -> guide filenames. A lens absent from this map gets NO guides.
#
# FILE-A vs FILE-B are mutually exclusive by filing date. FILE-A covers filings
# postmarked 23.12.2022 – 17.09.2026; FILE-B covers 18.09.2026 onward. The
# cover letter puts I-485 #1 at 22.03.2024 and #2 at "[filing date] 2026", i.e.
# imminent — both inside FILE-A's window as of the run date 2026-08-18.
# 🔴 IF THE FILING SLIPS PAST 17.09.2026, FILE-B GOVERNS AND THIS ROUTE IS WRONG.
# That is ~4 weeks out. Re-check the date before reusing this map.
# --------------------------------------------------------------------------
GUIDE_ROUTING: dict[str, list[str]] = {
    "duplicate-filing": [
        "LITIGATOR-ALGORITHM-I140-I485.md",
        "I-485-APPROVAL-MASTER-CHECKLIST.md",
    ],
    "public-charge": [
        "PUBLIC-CHARGE-STRATEGY-GUIDE.md",
        "I-485-PUBLIC-CHARGE-UNIVERSAL-GUIDE.md",
        "I-485-PUBLIC-CHARGE-ФАЙЛ-A-подано-до-18.09.2026-v1.2.md",
        "I-485-ПОЗИТИВНЫЕ-АРТЕФАКТЫ-каталог-v1.0.md",
    ],
    # The checklist is the only document in the set that records the posture of any
    # earlier application — adverse notices received, the continuous-lawful-status
    # answer, which office holds it. That posture is exactly what the cascade lens has
    # to reason about, and it is the piece a reviewer looking only at the new filing
    # cannot see.
    "cross-application-cascade": [
        "LITIGATOR-ALGORITHM-I140-I485.md",
        "I-485-APPROVAL-MASTER-CHECKLIST.md",
    ],
    # Deliberately thin. None of the guides carries a Visa Bulletin, and this lens
    # is explicitly forbidden to assert a cut-off date, so loading it with
    # public-charge material would be pure dilution.
    "visa-availability": [
        "LITIGATOR-ALGORITHM-I140-I485.md",
    ],
}

FILE_B_CUTOVER = "2026-09-18"


def build_guide_block(lens_id: str, guides_dir: pathlib.Path) -> str:
    """Guides routed to `lens_id`, wrapped in the provenance framing.

    Returns "" for a lens with no route — the twelve original lenses, whose
    corpus must stay byte-identical to R06 for the regression grid to mean
    anything.
    """
    names = GUIDE_ROUTING.get(lens_id, [])
    if not names:
        return ""
    parts = [GUIDE_PREAMBLE]
    for n in names:
        p = guides_dir / n
        if not p.exists():
            raise FileNotFoundError(
                f"routed guide missing: {p}\n"
                f"Routing names a file that is not on disk. Fix the route or the "
                f"corpus — do NOT silently send a lens without the guide it was "
                f"designed around.")
        parts.append(f"\n\n===== BEGIN REFERENCE: {n} =====\n\n"
                     f"{p.read_text(encoding='utf-8')}"
                     f"\n\n===== END REFERENCE: {n} =====\n")
    return "".join(parts)


def routed_lenses() -> list[str]:
    return sorted(GUIDE_ROUTING)


if __name__ == "__main__":
    import sys
    gd = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "private/guides-redacted")
    print(f"guides dir: {gd}")
    for lid, _ in EXTRA_LENSES:
        block = build_guide_block(lid, gd)
        print(f"  {lid:<18} guides={len(GUIDE_ROUTING.get(lid, [])):<2} "
              f"chars={len(block):>9,}  ~{len(block)/3.0:>8,.0f} tok (ESTIMATE)")
