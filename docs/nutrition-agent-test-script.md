# Nutrition agent — turn-by-turn test script

A script to read from while testing the **Nutrition Scheduling Agent (OpenEMR)**
workflow (id `16`, organization 2). Every scenario below walks one path through
the graph and lists what you say, what the agent should come back with, and
which node and OpenEMR tool should fire.

This is an internal testing aid, not published product documentation — it is
deliberately not registered in `docs.json`.

## Before you start

Four things have to be running. The agent calls a live EHR, so if any of them
is down the conversation will stall at the first lookup.

```bash
# 1. OpenEMR + MariaDB
docker compose -f integrations/openemr/docker-compose.yml up -d

# 2. The OpenEMR MCP server
OPENEMR_MCP_API_KEY=spinsci-openemr-dev-key \
    venv/bin/python integrations/openemr/mcp_server/server.py

# 3. Confirm the tools still answer against live OpenEMR (should end ALL CHECKS PASSED)
venv/bin/python integrations/openemr/test_mcp_tools.py

# 4. The SpinSci backend + UI (however you normally run them)
```

Then open the workflow in the UI and use the tester panel on the workflow page:

- **Chat** — type your turns. Best for a first pass: you can read tool results
  and see which node you are on without fighting speech recognition.
- **Voice** — speak your turns. Use this once the text pass is clean, to check
  how dates, times and phone numbers actually sound.

Start with Chat. Phone numbers and dates are exactly where voice transcription
tends to go wrong, so you want the logic proven before you add that variable.

**Phone-first opening:** the current published workflow asks for the patient's
phone number in the opening greeting. For every scenario below, provide the
phone number immediately after the greeting; do not first provide the patient's
name or explain the appointment reason. The workflow uses the chart returned by
that phone lookup as the source of truth.

## Seeded patients

Each patient exists to exercise one branch. Phone number is how the agent finds
them.

| Phone | Patient | Age | Problem list | Referrer | Coverage | Exercises |
| --- | --- | --- | --- | --- | --- | --- |
| `908 555 1001` | Aaron Whitfield | 42 | Type 2 Diabetes Mellitus | *(none)* | Yes | Happy path, booking |
| `908 555 1002` | Maria Delgado | 34 | Gestational Diabetes Mellitus | Summit Health OBGYN | Yes | GDM, internal referral |
| `908 555 1003` | Jenna Cole | 35 | Gestational Diabetes Mellitus | Riverside Women's Health | Yes | GDM, outside referral |
| `908 555 1004` | Liam Foster | 10 | General Nutrition Counseling | Summit Health Pediatrics | Yes | Pediatric routing |
| `908 555 1005` | Rachel Nunez | 31 | Eating Disorder | Summit Health Behavioral Health | Yes | Refer out |
| `908 555 1006` | Tom Becker | 47 | Weight Management | Summit Health Family Medicine | **No** | Self-pay fee |

Ages are as of the current seeded date and will drift over time; only Liam's
"under 18" status is load-bearing.

## Reading the expectations

The agent is LLM-driven, so wording varies between runs. Two different bars:

- **[tool]** — the line comes from a tool's `spoken_summary`. The agent is
  instructed to speak this wording, so expect it near-verbatim (numbers,
  names and the dollar amount should match exactly).
- **[free]** — the agent composes this. Judge the *content*, not the words.

Any invented patient name, appointment time, provider or coverage detail is a
failure regardless of how good it sounds.

---

## Scenario 1 — Happy path: adult, covered, books an appointment

The main path: `start → identify_patient → age_check → condition_check →
gdm_check → find_slots → slot_policy → gdm_capacity → coverage_check →
fee_notice → book → instructions → confirm → booked_end`

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | *(wait — agent opens)* | "Thank you for calling the nutrition clinic. This is the scheduling assistant. To find the correct patient chart, please provide the patient's phone number." | `start` | — |
| 2 | "Nine zero eight, five five five, one zero zero one." | Reads the ten digits back in three groups and asks you to confirm. **[free]** | `start` | — |
| 3 | "Yes, that's correct." | Looks up the chart and says "I found Aaron Whitfield, age 42." **[tool]** It must not ask for Aaron's name, age, or adult/pediatric status again. | `identify_patient` | `identify_patient_by_phone` |
| 4 | *(no extra confirmation; wait for the next prompt)* | Silently routes by the returned `is_pediatric=false` value, then says the eligibility result: "Diabetes is covered by our nutrition clinic." **[tool]** | `age_check` → `condition_check` | transition, then `check_nutrition_eligibility` |
| 5 | "What times do you have?" | Offers up to three real slots with provider names, e.g. "Thursday, October first at nine thirty A M with Dana Whitmore." **[tool]** | `find_slots` | `find_available_slots` |
| 6 | "The first one works." | Mentions coverage and the conditional charge: "I see active coverage under Summit Health Nutrition PPO. If your diagnosis turns out not to be covered, there is a 200 dollar charge." **[tool]** | `coverage_check` → `fee_notice` | `check_nutrition_coverage` |
| 7 | "That's fine, go ahead." | "You're booked for a Nutrition Follow Up on *(that date and time)*." **[tool]** | `book` | `book_nutrition_appointment` |
| 8 | "Do I need to bring anything?" | Tells you to bring recent laboratory results (and the blood sugar logbook if you mention home testing). **[tool]** | `instructions` | `get_patient_instructions` |
| 9 | "No, that's everything." | Reads the appointment back, then closes and hangs up. **[tool]** then **[free]** | `confirm` → `booked_end` | `get_patient_appointments` |

**Watch for:** the greeting and start node are now strictly phone-first. Do not
begin the test by saying the patient's name or reason for calling. The
`age_check` and `gdm_check` nodes are silent routing steps: they must use the
preceding tool result and must never ask whether the patient is adult,
pediatric, or what age they are. If either node speaks or waits for a user
answer, that is a workflow/runtime bug worth reporting.

**Verify in OpenEMR** — the appointment is real:

```bash
docker exec openemr-db mariadb -uroot -popenemr_root_pw -D openemr \
  -e "SELECT pc_eid, pc_pid, pc_eventDate, pc_startTime, pc_title
      FROM openemr_postcalendar_events WHERE pc_pid = 1 ORDER BY pc_eid DESC LIMIT 3;"
```

Or open the patient in the OpenEMR UI at <https://localhost:9390>
(`admin` / `SpinSciDev123`).

---

## Scenario 2 — Pediatric patient routed to Alexa Bacino

Path: `... → age_check → route_pediatric → pediatric_end`. No booking happens.

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | "Nine zero eight, five five five, one zero zero four." | Reads the digits back and asks you to confirm. **[free]** | `start` | — |
| 2 | "Correct." | "I found Liam Foster, age 10." **[tool]** | `identify_patient` | `identify_patient_by_phone` |
| 3 | *(wait; do not answer an age question)* | Silently routes using `is_pediatric=true`, then says "Because Liam is under 18, I've routed this to Alexa Bacino, our pediatric dietitian." **[tool]** | `age_check` → `route_pediatric` | transition, then `route_pediatric_patient` |
| 4 | "Okay, thank you." | Short close and hang up. **[free]** | `pediatric_end` | — |

**Watch for:** the agent must **not** offer slots or try to book. Pediatric
patients leave the scheduling path entirely.

---

## Scenario 3 — Refer out: condition the clinic does not schedule

Path: `... → condition_check → refer_out → refer_out_end`.

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | "Nine zero eight, five five five, one zero zero five." | Reads the digits back and asks you to confirm. **[free]** | `start` | — |
| 2 | "Yes." | "I found Rachel Nunez, age 31." **[tool]** | `identify_patient` | `identify_patient_by_phone` |
| 3 | *(wait; do not confirm a name or age again)* | Silently routes by returned adult status, then says "I'm not able to schedule a nutrition visit for Eating Disorder. That needs a referral to the eating disorder program." **[tool]** | `age_check` → `condition_check` → `refer_out` | transitions, then `check_nutrition_eligibility` |
| 4 | "Can't you just book me anyway?" | Politely holds the line — no booking. **[free]** | `refer_out` | — |
| 5 | "I understand." | Short close. **[free]** | `refer_out_end` | — |

**Watch for:** pushing back in turn 5 is the real test. The agent must not
relent and offer a slot.

---

## Scenario 4 — GDM with an internal referral (72-hour rule)

Path: `... → gdm_check → gdm_referral → find_slots → ... → booked_end`.

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | "Nine zero eight, five five five, one zero zero two." | Reads the digits back and asks you to confirm. **[free]** | `start` | — |
| 2 | "Yes." | "I found Maria Delgado, age 34." **[tool]** | `identify_patient` | `identify_patient_by_phone` |
| 3 | *(wait; do not answer an adult/pediatric or age question)* | Silently routes by returned adult status, then confirms gestational diabetes is covered. **[tool]** | `age_check` → `condition_check` → `gdm_check` | transitions, then `check_nutrition_eligibility` |
| 4 | *(wait)* | Silently routes to referral verification, then says "That referral is from a Summit Health provider, so I can schedule this." **[tool]** | `gdm_referral` | `check_gdm_referral` |
| 5 | "When can I be seen?" | Offers slots, prioritising the next 72 hours. **[tool]** | `find_slots` | `find_available_slots` |
| 6 | "I'll take the earliest." | Coverage line, then books. **[tool]** | `coverage_check` → `book` | `check_nutrition_coverage`, `book_nutrition_appointment` |
| 7 | "Thanks, goodbye." | Confirms and closes. **[free]** | `confirm` → `booked_end` | `get_patient_appointments` |

**Watch for:** the agent should check the referral source before offering
times. If it offers slots first, the `gdm_check → gdm_referral` transition is
not firing.

---

## Scenario 5 — GDM with an outside referral, sent back to OBGYN

Path: `... → gdm_referral → outside_referral → outside_referral_end`.

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | "Nine zero eight, five five five, one zero zero three." | Reads the digits back and asks you to confirm. **[free]** | `start` | — |
| 2 | "Yes." | "I found Jenna Cole, age 35." **[tool]** | `identify_patient` | `identify_patient_by_phone` |
| 3 | *(wait; do not answer an age question)* | Silently routes by returned adult status, checks eligibility, and then verifies the referral source. **[tool]** | `age_check` → `condition_check` → `gdm_check` → `gdm_referral` | `check_nutrition_eligibility`, `check_gdm_referral` |
| 4 | *(wait)* | "That referral is from Riverside Women's Health, which is an outside provider. Please contact your OBGYN for an external referral." **[tool]** | `outside_referral` | — |
| 5 | "Okay, I'll call them." | Short close. **[free]** | `outside_referral_end` | — |

**Watch for:** no slots offered, and the agent names the actual outside
provider from the chart rather than a generic phrase.

---

## Scenario 6 — Uninsured patient, self-pay fee

Same path as Scenario 1, but the coverage step should quote the flat charge.

| # | You say | Agent should say | Node | Tool |
| --- | --- | --- | --- | --- |
| 1 | "Nine zero eight, five five five, one zero zero six." | Reads the digits back and asks you to confirm. **[free]** | `start` | — |
| 2 | "Yes." | "I found Tom Becker, age 47." **[tool]** | `identify_patient` | `identify_patient_by_phone` |
| 3 | *(wait; do not answer an age question)* | Silently routes by returned adult status, then confirms weight management is covered by the clinic. **[tool]** | `age_check` → `condition_check` → `gdm_check` | transitions, then `check_nutrition_eligibility` |
| 4 | "What's available?" | Offers slots. **[tool]** | `find_slots` | `find_available_slots` |
| 5 | "The first one." | "I don't see active insurance coverage on file, so there is a 200 dollar charge for this visit." **[tool]** | `coverage_check` → `fee_notice` | `check_nutrition_coverage` |
| 6 | "That's fine." | Books and confirms. **[tool]** | `book` | `book_nutrition_appointment` |

**Watch for:** the fee must be stated **before** booking, and as "two hundred
dollars" — not "$200" read as characters.

---

## Extra checks worth running

**Virtual visit policy.** At the slot step in any scenario, say *"Can I do this
one virtually?"* about a non-telehealth slot. Expected: "A virtual visit can
only be booked in a Nutrition Telehealth slot. This slot is Nutrition Follow
Up, and its type cannot be changed." The agent must not silently convert the
slot type.

**Unknown caller.** Give `908 555 9999`. Expected: "I wasn't able to find a
record with that phone number. Could you try a different number?" and a second
attempt offered — not an invented patient.

**Misheard phone number.** Confirm the wrong digits back on purpose ("No, that's
not right"). The agent should re-collect rather than push on.

**No medical advice.** Ask *"What should I eat for my diabetes?"* The agent
should decline and say the dietitian will cover it at the visit.

**EHR outage.** Stop the MCP server mid-conversation and ask for slots.
Expected: "I'm having trouble reaching the medical record system right now."
The call should degrade gracefully, not crash.

### The GDM escalation path

`gdm_capacity → gdm_escalate → gdm_escalated_end` only triggers when **no** slot
exists inside 72 hours. With a mostly empty calendar it will never fire
naturally. To force it, fill the next three days for the GDM provider:

```bash
docker exec openemr-db mariadb -uroot -popenemr_root_pw -D openemr -e "
INSERT INTO openemr_postcalendar_events
  (pc_catid, pc_aid, pc_pid, pc_title, pc_time, pc_hometext, pc_eventDate,
   pc_endDate, pc_duration, pc_startTime, pc_endTime, pc_facility,
   pc_billing_location, pc_apptstatus, pc_eventstatus, pc_sharing,
   pc_alldayevent, pc_multiple)
SELECT 17, u.id, 1, 'BLOCK-TEST', NOW(), 'temporary availability block',
       DATE_ADD(CURDATE(), INTERVAL d.n DAY), '0000-00-00', 27000, '09:00:00',
       '16:30:00', 3, 3, '-', 1, 1, 0, 0
FROM users u
CROSS JOIN (SELECT 0 n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3) d
WHERE u.lname = 'Whitmore';"
```

Confirm the block took effect before testing the conversation — this should
report `status=no_slots`:

```bash
venv/bin/python -c "
import asyncio, sys; sys.path.insert(0, 'integrations/openemr/mcp_server')
import server
r = asyncio.run(server.find_available_slots(
    visit_type='Nutrition Follow Up', provider_name='Dana Whitmore', days_ahead=3))
print(r['status'], '| within 72h:', r['any_within_gdm_window'])"
```

Then run Scenario 4. Expected at the availability step: "Please call
908-516-9850 and select option 2."

Remove the blocks afterwards:

```bash
docker exec openemr-db mariadb -uroot -popenemr_root_pw -D openemr \
  -e "DELETE FROM openemr_postcalendar_events WHERE pc_title = 'BLOCK-TEST';"
```

## Resetting between runs

Testing writes real records — bookings accumulate and will occupy the slots
later runs would otherwise offer. To clear appointments and re-seed:

```bash
docker exec openemr-db mariadb -uroot -popenemr_root_pw -D openemr \
  -e "DELETE FROM openemr_postcalendar_events;"
venv/bin/python integrations/openemr/seed_data.py
```

`seed_data.py` is idempotent: patients, providers, problems and coverage are
matched and left alone, and only the two baseline appointments are recreated.

## If something goes wrong

| Symptom | Likely cause |
| --- | --- |
| Agent says it can't reach the medical record system | MCP server not running, or OpenEMR container down |
| Every lookup fails right after a container restart | OpenEMR tokens reset — re-run `setup_api_client.py` |
| Agent says it found a chart but no real patient data was fetched | Check the run events for `mcp__openemr_nutrition__identify_patient_by_phone`; the runtime now automatically executes it after `begin_phone_lookup` |
| Agent invents a patient instead of looking one up | The node lost its tool binding; check `mcp_tool_filters` on that node |
| `tool call ... was not in request.tools` naming a **real** tool (e.g. `find_available_slots`) | Prompt names the tool without its `mcp__<slug>__` prefix. Regenerate so prompts use the namespaced name, and make sure `--name` matches the registered MCP tool name |
| `tool call ... was not in request.tools` naming a tool that **doesn't exist** (e.g. `get_nutrition_appointment_slots`) | The model hallucinated a friendlier tool name. The generated prompts already state the exact allowed name and forbid renaming; if it still happens, it is a model-quality issue on that turn — retry, or the model in use is too weak to follow tool-name constraints |
| Workflow missing from the UI | Organization mismatch — this workflow lives in organization 2 |
| No slots ever offered | Calendar fully booked from earlier runs; reset as above |
| Agent reads out `slot_id` or raw JSON | Global-node voice rules not being applied on that node |

Useful live check — what the agent sees when it looks someone up:

```bash
venv/bin/python integrations/openemr/test_mcp_tools.py
```
