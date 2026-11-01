import { describe, expect, it } from "vitest";

import { agentHint, agentMentionToken, hasAgentMention, hintText, removeAgentMentions } from "@/lib/agentMessages";
import type { AgentRun, Workflow } from "@/lib/types";

const agent = { id: "a1", name: "laptop-claude" };
const run = (status: string) => ({ status }) as AgentRun;
const wf = (status: string) => ({ status }) as Workflow;

describe("agent messages", () => {
  it("builds, finds and removes the agent's mention", () => {
    const token = agentMentionToken(agent);
    expect(token).toBe("@[laptop-claude](agent:a1)");
    expect(hasAgentMention(`${token} use X`, "a1")).toBe(true);
    expect(hasAgentMention(`${token} use X`, "a2")).toBe(false);
    expect(removeAgentMentions(`${token} use X`, "a1")).toBe("use X");
    expect(removeAgentMentions(`Please ${token} use X`, "a1")).toBe("Please use X");
  });

  it("tells what the agent is doing", () => {
    expect(agentHint([run("completed"), run("running")], wf("running"))).toBe("working");
    expect(agentHint([run("queued")], wf("running"))).toBe("starting");
    expect(agentHint([run("completed")], wf("waiting_human"))).toBe("idle");
    expect(agentHint([], wf("paused"))).toBe("idle");
    expect(agentHint([], wf("finished"))).toBe("nothing_scheduled");
    expect(agentHint([], undefined)).toBe("nothing_scheduled");
  });

  it("words the line under the box", () => {
    expect(hintText("working", "laptop-claude", "plan")).toBe(
      "laptop-claude is working on the plan: it reads this straight away, without stopping.",
    );
    expect(hintText("working", "laptop-claude", "brainstorm")).toBe(
      "laptop-claude is working on the design: it reads this straight away, without stopping.",
    );
    expect(hintText("starting", "laptop-claude")).toBe("laptop-claude is about to start: it gets this as soon as it begins.");
    expect(hintText("idle", "laptop-claude")).toBe(
      "laptop-claude isn't working right now: it gets this when its next run starts, and every later step keeps it in mind.",
    );
    expect(hintText("nothing_scheduled", "laptop-claude")).toBe(
      "Nothing is scheduled for laptop-claude right now: it gets this if work on the task starts again.",
    );
  });
});
