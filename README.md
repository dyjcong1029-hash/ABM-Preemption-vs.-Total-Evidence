# ABM: Preemption vs. Total Evidence in Epistemic Deference

This repository develops a series of NetLogo agent-based models (ABMs) comparing **Preemption** and **Total Evidence** as strategies of epistemic deference.

The current core project contains three experiments:

- **Experiment 0:** a dynamic Bandit baseline with no expert testimony;
- **Experiment 1:** deference to an expert's raw evidence;
- **Experiment 2:** deference to an opaque, finite-precision expert credence.

The project does not assume that an expert has superior reasoning abilities. The expert and the laypeople use the same prior, likelihood model, and Thompson-sampling rule. The expert's only advantage is having more research opportunities.

## A Simple Classroom Story

Imagine a classroom with one teacher and ten students. The students sit in a circle. Each student talks only to the student on the left and the student on the right.

The teacher has had more professional training and has studied the problem for longer. In the model, this means that she has many more chances to test the two options before she teaches the class. The teacher is not assumed to be smarter or always right. She and the students use the same way of reasoning. She is usually better informed because she has more experience.

The students are not passive. They test the options themselves, learn from their own results, and share those results with their neighbors.

When the teacher teaches the class, the students can respond in two ways:

- **Preemption:** a student sets aside what she learned before and bases her judgment on what the teacher teaches.
- **Total Evidence:** a student takes the teacher's lesson seriously but combines it with what she and her classmates learned.

In both cases, the students continue to learn after the lesson. The difference is whether they keep or set aside what they learned before the teacher spoke.

The three experiments tell this classroom story in stages:

- **Experiment 0 — Professional training:** the teacher studies for longer and gets more experience. The experiment asks whether this alone makes her better informed on average.
- **Experiment 1 — Teaching evidence:** the teacher shows the students the individual results from her earlier study.
- **Experiment 2 — Teaching a judgment:** the teacher does not show her evidence. She only tells the students how confident she is.

## Research Question

When laypeople defer to a single expert, what should they do with information they already possess?

- **Preemption:** replace the pre-intervention basis of judgment with the expert input.
- **Total Evidence:** retain the layperson's previous information and add the expert input.

The models compare the dynamic consequences of these rules. A belief changes an agent's next action; that action determines which evidence becomes observable; new evidence is then shared locally and affects later actions. The object of study is therefore not merely a one-step Bayesian calculation, but a feedback process:

```text
belief → action → observed evidence → local communication → revised belief
```

## Shared Bandit Environment

All three experiments use the same basic environment:

- one teacher (the expert) and ten students (the laypeople);
- the students sit in a ring and share first-hand observations with their two neighbors;
- messages arrive with a one-round delay and are not forwarded;
- option A succeeds with probability 0.50;
- option B succeeds with probability 0.55 in the **B-good** world and 0.45 in the **B-bad** world;
- agents do not know which world they inhabit;
- all agents use the same prior, likelihood model, Bayesian updating, and Thompson sampling;
- the teacher completes five pulls per round for the first 25 rounds: 125 research opportunities;
- each student completes one pull per round over 500 rounds;
- the teacher's advantage comes from longer professional training and more research opportunities, not from a fixed reliability score.

The main outcome is **cumulative expected regret**: the expected payoff lost by choosing the worse option. Each incorrect choice adds 0.05 regret, so lower values are better.

## Experiment 0 — Dynamic Bandit Baseline

Experiment 0 represents the teacher's professional training before she teaches the class. The teacher has studied for longer and has more research experience than the students. She does not teach them yet. The experiment asks whether longer training alone creates an average but fallible expert advantage.

### Main findings

1. **Expertise is average, not absolute.** At round 25, the expert assigns more probability to the true world than the laypeople network on average:

   - B-good: expert 0.694, laypeople 0.641;
   - B-bad: expert 0.699, laypeople 0.638.

   However, the expert outperforms the corresponding laypeople network mean in only 60.4% of B-good runs and 69.2% of B-bad runs. More research makes the expert more reliable on average but does not eliminate error.

2. **Learning is path-dependent and world-asymmetric.** Mean cumulative regret is 2.100 in B-good and 3.298 in B-bad. In B-bad, the informative option B is also the worse action, so continued learning carries an exploration cost.

3. **The communication network changes behavior.** Turning peer sharing on reduces regret by 3.715 in B-good and 2.690 in B-bad relative to matched no-sharing runs. Local communication therefore affects later choices and evidence production; the network is not merely decorative.

Experiment 0 establishes the baseline but does not adjudicate between Preemption and Total Evidence.

## Experiment 1 — Evidence Deference

At the intervention boundary—after round 25 and before round 26—the expert broadcasts 125 uniquely identified arm–outcome records. Laypeople can inspect and process the raw evidence.

The active evidential basis is defined as follows:

- **No Deference:** retain the 75 pre-intervention self/neighbor records and do not use the expert packet for decisions;
- **E-Preemption:** replace those 75 records with the expert's 125 records;
- **E-Total Evidence:** use the deduplicated union of the 75 local records and 125 expert records.

All policies continue to learn from new self and neighbor evidence after the intervention. Preemption is a one-time replacement of the active evidential basis, not a permanent refusal to think independently.

### Main result

Paired difference in post-intervention regret:

| World | E-Total Evidence − E-Preemption | 95% paired interval |
|---|---:|---:|
| B-good | -0.381 | [-0.531, -0.241] |
| B-bad | -0.410 | [-0.480, -0.340] |

Negative values favor Total Evidence. When the expert packet points in the wrong direction, retained local evidence also accelerates recovery. In the trajectory sample, median recovery delay is 9 versus 45 rounds in B-good and 21 versus 34 rounds in B-bad for E-Total Evidence and E-Preemption, respectively.

The robust conclusion concerns finite-horizon action loss. The model does not show that Total Evidence produces a more accurate final credence in every world.

## Experiment 2 — Opaque Credence Deference

Experiment 2 removes access to the expert's evidence and reasoning. Laypeople receive only a finite-precision credence report.

The expert's exact private probability is placed into one of ten bins:

```text
[0.0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]
```

A message might therefore mean “the expert's credence is approximately 0.65.” Laypeople cannot observe the expert's actions, outcomes, evidence sequence, exact credence, or inferential process.

The evidential force of each message bin is estimated from expert-only Bandit trajectories, checked on a disjoint held-out sample, and frozen before the main experiment.

- **No Deference:** keep the pre-intervention lay credence unchanged;
- **C-Preemption:** return to the common prior and add only the evidential force of the expert report;
- **C-Total Evidence:** retain the layperson's pre-intervention log odds and add the evidential force of the expert report.

### Main result

| World | C-Total Evidence − C-Preemption | 95% paired interval |
|---|---:|---:|
| B-good | -0.406 | [-0.549, -0.272] |
| B-bad | -0.478 | [-0.539, -0.417] |

These differences correspond to approximately 8.1 fewer incorrect choices per layperson in B-good and 9.6 fewer in B-bad over rounds 26–500.

The advantage is especially visible when the coarse expert report points in the wrong direction. Preemption exposes all laypeople to the same mistaken report after removing their previous informational basis; Total Evidence preserves dispersed local information that can partially counteract it.

An exact-credence condition is retained only as a regression test. Under the model's shared-prior, shared-likelihood, and independent-evidence assumptions, an exact expert credence is a sufficient statistic and reproduces the evidence-deference trajectory. The main Experiment 2 treatment instead uses a deliberately lossy, finite-precision report.

## Results at a Glance

| Experiment | Expert input | Central conclusion |
|---|---|---|
| 0 | None | Additional research generates an average but fallible expert advantage; selective sampling and local communication create dynamic path dependence. |
| 1 | 125 raw observations | Retaining independent local evidence lowers finite-horizon regret relative to replacing it. |
| 2 | One opaque credence-bin message | Total Evidence remains more robust under lossy communication, especially when the expert report is misleading. |

## Overall Interpretation

Within the current idealized environment, the most defensible conclusion is:

> A fallible expert can have a genuine average epistemic advantage without being infallible. When laypeople already possess independent, correctly interpreted information, discarding it at the moment of deference creates a dynamic cost. This occurs both when the expert transmits raw evidence and when the expert transmits only an opaque, finite-precision credence.

This is not a general proof that Total Evidence is always philosophically correct. Under independent evidence and correct Bayesian models, retaining more valid information already has a theoretical advantage. The contribution of the ABM is to show and quantify how that initial difference propagates through action selection, subsequent evidence production, network communication, recovery, and finite-time payoff.

## Scope and Limitations

The current conclusions depend on several strong assumptions:

- a single honest expert;
- a common prior and a shared, correct likelihood model;
- identical inferential abilities;
- conditionally independent expert and lay evidence;
- no duplicated evidence, strategic reporting, communication cost, or transmission error;
- a fixed 500-round horizon;
- known semantics for the expert's finite-precision report.

The models do not yet address multiple experts, disagreement aggregation, unknown reliability, evidence overlap, different priors, deception, or unequal inferential competence.

An inferential-structure experiment is not part of the current core sequence: because the expert's advantage is defined only by additional research opportunities, the expert and laypeople currently share the same inferential structure.

## Validation

- Experiment 0: 1,000 main runs; 36/36 model and analysis checks passed.
- Experiment 1: 3,000 main runs; 33/33 pre-specified checks passed.
- Experiment 2: 3,000 main runs; 13/13 calibration checks and 21/21 formal/model checks passed.

Policy comparisons use matched world × seed blocks. Reported intervals describe uncertainty from finite simulation repetitions; they are not sampling-error estimates for a real-world population.

## Repository Structure

- `models/`: NetLogo model files
- `data/`: BehaviorSpace output
- `code/`: R scripts for analysis
- `figures/`: plots and visualizations

## Software

The current experiments were run with:

- NetLogo 7.0.3
- R 4.5.3
