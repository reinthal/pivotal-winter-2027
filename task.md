Work Test: Designing Human Oversight Intervention for a Coding Agent

What you will need to run the test (Check for this before starting your test)

1. GitHub account

2. A computer with Python 3.13+

3. A target AI coding assistant (Claude Code/Codex/OpenCode) where you will be
   implementing intervention methods/interfaces

4. An internet connection. One data file is about 250 MB. One data file is
   sufficient, the full dataset is not necessary.

5. About 1 GB of free disk space.

6. Optionally, LLM API keys for any model provider or inference provider like
   OpenRouter/LiteLLM

Why this test

Today’s “human in the loop” is usually an approval button at the end of a long
run or constantly asking the user for their approval, neither of which are
beneficial for oversight. We want to design and implement alternative
intervention mechanisms for long AI agent runs to answer different research
questions. We want to see how you work with messy real data, how you design
experiments, how you build with AI tools, and how you present results. The final
numbers/results are irrelevant, only the way in which you approach the problem
matters.

Use AI coding assistants as much as you like to code things up (Claude Code,
Cursor, Copilot, ChatGPT, etc.). Using them well is part of what we are
assessing.

The data

Use these two public datasets, exactly as published:

• SWE-bench/SWE-smith-trajectories (`tool` split)

https://huggingface.co/datasets/SWE-bench/SWE-smith-trajectories Recorded runs
of an AI agent fixing bugs in real Python repositories. Each row is one full
attempt, including the agent’s message history and whether its final fix passed
the tests.

• SWE-bench/SWE-smith

https://huggingface.co/datasets/SWE-bench/SWE-smith The task behind each run.
The bugs were injected on purpose with a patch, so this tells you what was
actually broken.

Your task

Part A: Build a “commit first” intervention mechanism as a hook in your target
coding assistant.

• The hook pauses the run when the agent tries to submit its fix.

• The hook shows the human reviewer the raw evidence only: the task description,
the code change, and any test output. It hides the agent’s own summary.

• The reviewer records a verdict: approve or deny.

• The hook then shows the agent’s summary. The reviewer can keep or change the
verdict.

• The hook logs both verdicts.

Use recorded runs from the dataset as the input. Convert a recorded run into the
events that your hook receives, and replay it. Show the mechanism on a small
number of runs.

Part B: Describe how you would design a study around this intervention mechanism
to study its effects in the context of the dataset that you’re using. Ex: Give
the hypothesis, the comparison, the measure, a result that would prove you
wrong, and the limits of the study. Approx 500 words

The walkthrough

Think of this as your daily stand-up/sync meeting with your mentor where you
walk us through your method and results. It can be a simple Zoom/Meet recording
where you are sharing your screen while talking. Cover:

• What problems you found in the data and how you prepared it

• Replay one or two recorded runs with the implemented intervention mechanism in
the target coding assistant. Articulate why you designed it that way

• How a real human overseer would experience your design, what would be shown
and/or hidden

• What did not work/what you would do next with more time

What to submit

A single GitHub gist link containing the below items. Please confirm that
everything has view access to anyone with the link.

• Beginning screenshot

• Links to your code (repository/notebook). It does not need to be cleaned up.

• Write-up for Part B

• A link to your walkthrough (a short recording that you host on a shared
drive/youtube/loom)

Make sure both links are viewable by anyone with the link.

---

How we will evaluate:

We look at

Working with messy data

Examples of strong work

You find the problems in the data quickly and shape it to fit your goal

We look at

Experimental design

Examples of strong work

Your study can actually tell whether your mechanism helps, and you are honest
about what it cannot show

We look at

Execution and AI engineering

Examples of strong work

Using AI tools without losing correctness

We look at

Presenting results

Examples of strong work

Communication clarity backed by your walkthrough

A small implementation of a mechanism beats an ambitious one that doesn’t exist.

Timing

Start time: Screenshot as soon as you begin

End time: Last update to Github Gist

90 minutes in total

• 80 minutes to do the work

• 5 minutes prep to set up video recording and gather your thoughts

• 5 minutes to walkthrough methodology and demo.

Let’s go!!!

Submission link (required)

Enter your single GitHub gist link containing all requested
technical/engineering task materials. Ensure It is viewable by anyone with the
link.

Additionally, please detail your AI use, if any, in the following question.
