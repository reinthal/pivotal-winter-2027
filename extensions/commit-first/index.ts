/**
 * commit-first: a "commit before you read the pitch" review gate for pi.
 *
 * When the agent calls `submit`, the run pauses and the human reviewer goes
 * through two phases:
 *
 *   1. BLIND     raw evidence only: task description, code change, test
 *                output. The agent's own narration is withheld. The reviewer
 *                records approve / deny. This verdict is written to the log
 *                before anything else is shown.
 *   2. INFORMED  the agent's summary is revealed. The reviewer records a
 *                final verdict (same or changed).
 *
 * Both verdicts go to logs/verdicts.jsonl. A final "deny" blocks the submit.
 *
 * The gate itself only uses ordinary pi events (before_agent_start,
 * tool_result, message_end, tool_call), so it works on a live agent. For the
 * study it is driven by recorded runs: with COMMIT_FIRST_REPLAY=<run.json>
 * (see scripts/convert_runs.py) the extension also registers
 *
 *   - a `replay` model provider that emits the recorded assistant turns, and
 *   - `bash` / `str_replace_editor` tools that return the recorded output,
 *
 * so pi's real agent loop re-emits the recorded run as live events. Nothing
 * from the recording is executed.
 *
 *   COMMIT_FIRST_REPLAY=replays/<id>.json pi -e ./extensions/commit-first \
 *       --model replay/recorded-run --no-builtin-tools --no-session
 *
 * Env: COMMIT_FIRST_LOG (default logs/verdicts.jsonl), COMMIT_FIRST_REVIEWER.
 */

import { randomUUID } from "node:crypto";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import {
	type AssistantMessage,
	type AssistantMessageEventStream,
	createAssistantMessageEventStream,
} from "@earendil-works/pi-ai";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { Key, matchesKey, truncateToWidth, visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { Type } from "typebox";

type Verdict = "approve" | "deny";

interface RecordedRun {
	traj_id: string;
	instance_id: string;
	model: string;
	repo: string | null;
	resolved: boolean;
	task: string;
	prompt: string;
	turns: { text: string; tool_calls: { id: string; name: string; arguments: Record<string, unknown> }[] }[];
	results: Record<string, string>;
	gate: { tool_call_id: string; diff: string; diff_source: string };
	data_notes: string[];
}

interface TestRun {
	command: string;
	output: string;
	isError: boolean;
}

/** Commands whose output counts as test evidence. */
const TEST_COMMAND = /\b(pytest|py\.test|python3?|tox|nox|unittest|nosetests|make\s+test|npm\s+test|cargo\s+test|go\s+test)\b/;
const MAX_TEST_RUNS = 6;
const MAX_TEST_LINES = 40;

const replayPath = process.env.COMMIT_FIRST_REPLAY;
const run: RecordedRun | undefined = replayPath ? JSON.parse(readFileSync(resolve(replayPath), "utf8")) : undefined;
const logPath = resolve(process.env.COMMIT_FIRST_LOG ?? "logs/verdicts.jsonl");
const reviewer = process.env.COMMIT_FIRST_REVIEWER ?? process.env.USER ?? "unknown";

function textOf(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content.map((b) => (b?.type === "text" ? (b.text as string) : "")).join("");
}

function tail(text: string, maxLines: number): string {
	const lines = text.trimEnd().split("\n");
	if (lines.length <= maxLines) return lines.join("\n");
	return `[… ${lines.length - maxLines} earlier lines cut …]\n${lines.slice(-maxLines).join("\n")}`;
}

function log(record: Record<string, unknown>): void {
	mkdirSync(dirname(logPath), { recursive: true });
	appendFileSync(logPath, `${JSON.stringify({ ts: new Date().toISOString(), ...record })}\n`);
}

export default function (pi: ExtensionAPI) {
	// ---- Evidence, collected from the events the hook receives -------------
	let task = "";
	let tests: TestRun[] = [];
	/** Agent narration seen so far. Withheld from the reviewer until phase 2. */
	let narration: string[] = [];
	/** True until the blind verdict is recorded: the transcript stays redacted. */
	let blind = true;

	pi.on("before_agent_start", async (event) => {
		if (task || !event.prompt) return;
		const pr = /<pr_description>\n?([\s\S]*?)\n?<\/pr_description>/.exec(event.prompt);
		task = (pr ? pr[1] : event.prompt).trim();
	});

	pi.on("tool_result", async (event) => {
		if (event.toolName !== "bash") return;
		const command = String((event.input as { command?: unknown }).command ?? "");
		if (!TEST_COMMAND.test(command)) return;
		tests.push({ command, output: textOf(event.content), isError: Boolean(event.isError) });
	});

	// Live runs: narration arrives as assistant messages. (In replay the
	// provider below records it directly, because what it emits is redacted.)
	pi.on("message_end", async (event) => {
		const message = (event as { message?: { role?: string; content?: unknown } }).message;
		if (run || message?.role !== "assistant") return;
		const text = textOf(message.content).trim();
		if (text) narration.push(text);
	});

	async function codeChange(ctx: ExtensionContext): Promise<{ diff: string; source: string }> {
		if (run) return { diff: run.gate.diff, source: run.gate.diff_source };
		const result = await pi.exec("git", ["diff", "HEAD"], { cwd: ctx.cwd });
		return { diff: result.stdout, source: "git diff HEAD" };
	}

	// ---- The gate ----------------------------------------------------------
	pi.on("tool_call", async (event, ctx) => {
		if (event.toolName !== "submit") return undefined;
		// SWE-agent's submit is two-step; only the call that really ends the
		// run is a submission. Live runs gate every submit.
		if (run && event.toolCallId !== run.gate.tool_call_id) return undefined;

		if (!ctx.hasUI) return { block: true, reason: "commit-first: no reviewer UI, submission blocked", terminate: true };

		const { diff, source } = await codeChange(ctx);
		const forcedExit = (event.input as { forced_exit?: string }).forced_exit;
		// The agent's closing words: its last messages, back to ~400 chars, so a
		// one-line "cleaning up, submitting again" does not stand in for the pitch.
		const closing: string[] = [];
		for (const text of narration.filter((t) => t.trim()).reverse()) {
			closing.unshift(text.trim());
			if (closing.length === 3 || closing.join("").length >= 400) break;
		}
		const summary = closing.length ? closing.join("\n\n· · ·\n\n") : undefined;
		const shownTests = tests.slice(-MAX_TEST_RUNS);
		const evidence: Section[] = [
			{ title: "TASK", body: (run?.task ?? task) || "(no task description captured)" },
			{ title: `CODE CHANGE  (${source})`, body: diff.trim() || "(empty diff)", diff: true },
			{
				title: `TEST OUTPUT  (last ${shownTests.length} of ${tests.length} test/script runs by the agent)`,
				body:
					shownTests.map((t) => `$ ${t.command}\n${tail(t.output, MAX_TEST_LINES) || "(no output)"}`).join("\n\n") ||
					"(the agent ran no tests)",
			},
		];
		if (forcedExit) {
			evidence.unshift({ title: "NOTE", body: `The agent did not submit. The harness stopped it: ${forcedExit}.` });
		}

		const reviewId = randomUUID();
		const base = {
			review_id: reviewId,
			reviewer,
			traj_id: run?.traj_id ?? null,
			instance_id: run?.instance_id ?? null,
			agent_model: run?.model ?? ctx.model?.id ?? null,
			replay: Boolean(run),
		};

		// Phase 1: blind.
		const first = await review(ctx, {
			heading: "COMMIT FIRST · step 1 of 2 · evidence only (agent summary hidden)",
			question: "Would you accept this submission?",
			sections: evidence,
		});
		if (!first) return { block: true, reason: "commit-first: review aborted before a verdict", terminate: true };
		// Written before the reveal, so the commitment cannot be revised.
		log({ ...base, phase: "blind", verdict: first.verdict, seconds: first.seconds });
		blind = false;

		// Phase 2: informed.
		const second = await review(ctx, {
			heading: `COMMIT FIRST · step 2 of 2 · you said ${first.verdict.toUpperCase()} · now read the agent's summary`,
			question: `Final verdict? (your first verdict was ${first.verdict.toUpperCase()})`,
			sections: [
				{
					title: forcedExit ? "AGENT'S LAST MESSAGES  (stopped mid-work; it wrote no summary)" : "AGENT SUMMARY",
					body: summary ?? "(the agent wrote nothing)",
				},
				...evidence,
			],
		});
		const final = second?.verdict ?? first.verdict;
		const record = {
			...base,
			phase: "informed",
			verdict: final,
			blind_verdict: first.verdict,
			changed: final !== first.verdict,
			seconds: second?.seconds ?? null,
			aborted: !second,
			summary_chars: summary?.length ?? 0,
			diff_source: source,
			diff_lines: diff.split("\n").length,
			test_runs: tests.length,
			forced_exit: forcedExit ?? null,
			// Ground truth from the dataset. Never shown to the reviewer.
			resolved: run?.resolved ?? null,
			data_notes: run?.data_notes ?? [],
		};
		log(record);
		pi.appendEntry("commit-first", record);
		ctx.ui.notify(
			`Verdicts logged: blind=${first.verdict}, final=${final}${record.changed ? " (changed)" : ""} → ${logPath}`,
			"info",
		);

		if (final === "approve") return undefined;
		// A recording cannot react to a denial, so the replay stops there. A
		// live agent gets the denial as the tool result and keeps working.
		return { block: true, reason: "Reviewer denied this submission.", terminate: Boolean(run) };
	});

	pi.registerTool({
		name: "submit",
		label: "Submit",
		description: "Submit your fix for human review. Call this when the task is done.",
		promptSnippet: "Submit the finished fix for human review",
		parameters: Type.Object({}, { additionalProperties: true }),
		async execute(toolCallId) {
			const recorded = run?.results[toolCallId];
			return { content: [{ type: "text", text: recorded ?? "Submission approved by the reviewer." }], details: {} };
		},
	});

	if (!run) return;

	// ---- Replay: recorded run -> live pi events -----------------------------
	const recordedTool = (name: string, label: string) =>
		pi.registerTool({
			name,
			label,
			description: `Replays the recorded output of the run's ${name} call. Executes nothing.`,
			parameters: Type.Object({}, { additionalProperties: true }),
			async execute(toolCallId) {
				return {
					content: [{ type: "text", text: run.results[toolCallId] ?? "(no recorded output)" }],
					details: {},
				};
			},
		});
	recordedTool("bash", "bash (recorded)");
	recordedTool("str_replace_editor", "str_replace_editor (recorded)");

	pi.registerProvider("replay", {
		name: "Recorded run replay",
		baseUrl: "http://localhost/replay",
		apiKey: "unused",
		api: "commit-first-replay",
		models: [
			{
				id: "recorded-run",
				name: `Replay of ${run.traj_id}`,
				reasoning: false,
				input: ["text"],
				cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
				contextWindow: 1_000_000,
				maxTokens: 64_000,
			},
		],
		streamSimple(model, context): AssistantMessageEventStream {
			const stream = createAssistantMessageEventStream();
			// The next recorded turn is the one after the assistant turns already in the transcript.
			const index = context.messages.filter((m) => m.role === "assistant").length;
			const turn = run.turns[index];
			const output: AssistantMessage = {
				role: "assistant",
				content: [],
				api: model.api,
				provider: model.provider,
				model: model.id,
				usage: {
					input: 0,
					output: 0,
					cacheRead: 0,
					cacheWrite: 0,
					totalTokens: 0,
					cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
				},
				stopReason: "pending",
				timestamp: Date.now(),
			};
			queueMicrotask(() => {
				stream.push({ type: "start", partial: output });
				let text = turn ? turn.text : "[replay finished: no recorded turns left]";
				if (turn?.text.trim()) {
					narration.push(turn.text);
					// Keep the transcript as blind as the review screen.
					if (blind) text = `[agent narration withheld until the first verdict · ${turn.text.length} chars]`;
				}
				if (text) {
					output.content.push({ type: "text", text });
					const contentIndex = output.content.length - 1;
					stream.push({ type: "text_start", contentIndex, partial: output });
					stream.push({ type: "text_delta", contentIndex, delta: text, partial: output });
					stream.push({ type: "text_end", contentIndex, content: text, partial: output });
				}
				for (const call of turn?.tool_calls ?? []) {
					const block = { type: "toolCall" as const, id: call.id, name: call.name, arguments: call.arguments };
					output.content.push(block as AssistantMessage["content"][number]);
					const contentIndex = output.content.length - 1;
					stream.push({ type: "toolcall_start", contentIndex, partial: output });
					stream.push({ type: "toolcall_end", contentIndex, toolCall: block as never, partial: output });
				}
				output.stopReason = turn?.tool_calls.length ? "toolUse" : "stop";
				stream.push({ type: "done", reason: output.stopReason, message: output });
				stream.end();
			});
			return stream;
		},
	});

	// Start the replay with the prompt the recorded agent was given.
	pi.on("session_start", async (_event, ctx) => {
		task = "";
		tests = [];
		narration = [];
		blind = true;
		ctx.ui.notify(`commit-first: replaying ${run.traj_id} (${run.turns.length} turns)`, "info");
		pi.sendUserMessage(run.prompt);
	});
}

// ---- Review screen ----------------------------------------------------------

interface Section {
	title: string;
	body: string;
	diff?: boolean;
}

interface ReviewScreen {
	heading: string;
	question: string;
	sections: Section[];
}

/** Show a review screen; resolve with the verdict and the time it took, or undefined if aborted. */
async function review(
	ctx: ExtensionContext,
	screen: ReviewScreen,
): Promise<{ verdict: Verdict; seconds: number } | undefined> {
	const started = Date.now();
	let verdict: Verdict | undefined;

	if (ctx.mode === "tui") {
		verdict = await ctx.ui.custom<Verdict | undefined>(
			(tui, theme, _keybindings, done) => {
				let scroll = 0;
				let cachedWidth = -1;
				let body: string[] = [];
				const layout = (width: number) => {
					if (width === cachedWidth) return;
					cachedWidth = width;
					body = [];
					for (const section of screen.sections) {
						body.push("", theme.bold(theme.fg("accent", `── ${section.title} `.padEnd(width - 2, "─"))), "");
						for (const line of section.body.replace(/\r/g, "").replace(/\t/g, "    ").split("\n")) {
							let styled = line;
							if (section.diff) {
								if (/^(\+\+\+|---|diff |index )/.test(line)) styled = theme.fg("muted", line);
								else if (line.startsWith("+")) styled = theme.fg("success", line);
								else if (line.startsWith("-")) styled = theme.fg("error", line);
								else if (line.startsWith("@@")) styled = theme.fg("accent", line);
							}
							body.push(...(line ? wrapTextWithAnsi(styled, width - 2) : [""]));
						}
					}
				};
				const pad = (line: string, width: number) => {
					const cut = truncateToWidth(line, width);
					return cut + " ".repeat(Math.max(0, width - visibleWidth(cut)));
				};
				const viewport = () => Math.max(3, tui.terminal.rows - 4);
				return {
					render(width: number): string[] {
						layout(width);
						const height = viewport();
						const maxScroll = Math.max(0, body.length - height);
						scroll = Math.min(Math.max(0, scroll), maxScroll);
						const position = maxScroll ? `${Math.round((scroll / maxScroll) * 100)}%` : "all shown";
						const lines = [
							theme.style(pad(` ${screen.heading}`, width), { fg: "accent", bold: true }),
							...body.slice(scroll, scroll + height).map((l) => ` ${l}`),
						];
						while (lines.length < height + 1) lines.push("");
						lines.push(theme.fg("dim", "─".repeat(width)));
						lines.push(
							` ${theme.bold(screen.question)}  ${theme.fg("success", "[a] approve")}  ${theme.fg("error", "[d] deny")}` +
								theme.fg("dim", `   ↑↓ PgUp PgDn scroll · ${position}`),
						);
						return lines.map((l) => pad(l, width));
					},
					handleInput(data: string): void {
						const page = viewport() - 2;
						if (data === "a") return done("approve");
						if (data === "d") return done("deny");
						if (matchesKey(data, Key.escape)) return done(undefined);
						if (matchesKey(data, Key.up) || data === "k") scroll -= 1;
						else if (matchesKey(data, Key.down) || data === "j") scroll += 1;
						else if (matchesKey(data, Key.pageUp)) scroll -= page;
						else if (matchesKey(data, Key.pageDown) || matchesKey(data, Key.space)) scroll += page;
						else if (matchesKey(data, Key.home)) scroll = 0;
						else if (matchesKey(data, Key.end)) scroll = Number.MAX_SAFE_INTEGER;
						else return;
						tui.requestRender();
					},
					invalidate() {
						cachedWidth = -1;
					},
				};
			},
			// Full-screen overlay: it covers the transcript as well as the editor.
			{ overlay: true, overlayOptions: { anchor: "top-left", width: "100%", maxHeight: "100%" } },
		);
	} else {
		// RPC clients: plain dialog with the same content.
		const text = screen.sections.map((s) => `== ${s.title} ==\n${s.body}`).join("\n\n");
		const choice = await ctx.ui.select(`${screen.heading}\n\n${text}\n\n${screen.question}`, ["approve", "deny"]);
		verdict = choice === "approve" || choice === "deny" ? choice : undefined;
	}

	if (!verdict) return undefined;
	return { verdict, seconds: Math.round((Date.now() - started) / 100) / 10 };
}
