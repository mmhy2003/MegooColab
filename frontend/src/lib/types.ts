import type { components } from "@/lib/api-types";

type S = components["schemas"];

export type User = S["UserOut"];
export type Role = User["role"];
export type Team = S["TeamSummary"];
export type TeamDetail = S["TeamDetail"];
export type Project = S["ProjectOut"];
export type Column = S["ColumnOut"];
export type Label = S["LabelOut"];
export type Repo = S["RepoOut"];
export type Task = S["TaskOut"];
export type TaskWorkflow = S["TaskWorkflowOut"];
export type Workflow = S["WorkflowOut"];
export type WorkflowStage = TaskWorkflow["stage"];
export type WorkflowStatus = TaskWorkflow["status"];
export type WorkflowNeeds = NonNullable<TaskWorkflow["needs"]>;
export type DocumentInfo = S["DocumentInfo"];
export type DocumentDetail = S["DocumentOut"];
export type FollowUpOut = S["FollowUpOut"];
// two backend schemas are named FollowUpRef, so the generator qualifies both with their module
export type FollowUpRef = S["app__workflow__schemas__FollowUpRef"];
export type DocKind = S["DocKind"];
export type TaskType = Task["type"];
export type Priority = Task["priority"];
export type ColumnCategory = Column["category"];
// images: always sent by the server (empty when none); optional here so a hand-built item needs none
export type ActivityItem = Omit<S["ActivityItem"], "images"> & Partial<Pick<S["ActivityItem"], "images">>;
export type Attachment = S["AttachmentOut"];
export type Sprint = S["SprintOut"];
export type BurndownPoint = S["BurndownPoint"];
export type VelocityPoint = S["VelocityPoint"];
export type AuditEntry = S["AuditOut"];
export type AdminSettings = S["AdminSettingsOut"];
export type Agent = S["AgentOut"];
export type RunnerInfo = S["RunnerInfo"];
export type Machine = S["MachineOut"];
export type Updates = S["UpdatesOut"];
export type AgentProgram = S["AgentProgram"];
export type ModelOption = S["ModelOption"];
export type Passkey = S["PasskeyOut"];
export type AnswerMode = S["AnswerMode"];
export type AdminAgent = S["AdminAgentOut"];
export type AccessToken = S["TokenOut"];
export type TokenScope = S["TokenScope"];
export type CreatedToken = S["CreatedTokenOut"];
export type ProjectAgent = S["ProjectAgentOut"];
export type AgentRun = S["RunOut"];
export type RunPolicy = S["RunPolicy"];

/** The `question` of an activity item with type "question" (the API types it as a loose object). */
export type QuestionChoice = { id: string; label: string; description?: string | null; recommended?: boolean };
export type ActivityQuestion = {
  id: string;
  body: string;
  choices: QuestionChoice[];
  status: "open" | "answered" | "withdrawn";
  mockup: { id: string; version: number; title: string } | null;
  answered_by: { id: string; name: string } | null;
  answer_choice: string | null;
  answer_text: string | null;
  /** the form the agent asked with, drawn in place of the choices */
  form: SurfaceMessage | null;
  /** what the person sent with the form; null when they answered in their own words */
  answer_data: FormValues | null;
};
export type MockupInfo = { id: string; version: number; title: string; choices: string[]; created_at: string };
/** A form's values: the whole data model of its A2UI surface. */
export type FormValues = Record<string, unknown>;
/** An A2UI v1.0 `createSurface` message, as the backend stores it: a form question's or a card's. */
export type SurfaceMessage = {
  version: "1.0";
  createSurface: { surfaceId: string; catalogId: string; components: Record<string, unknown>[]; dataModel?: FormValues };
};
/** The `card` of an activity item with type "card" (the API types it as a loose object). */
export type ActivityCard = {
  id: string;
  title: string;
  text: string;
  surface: SurfaceMessage;
  /** the agent whose run showed it; null for a person's own agent (the item's actor) or a deleted agent */
  agent: { id: string; name: string } | null;
};
export type ReviewDetail = S["ReviewOut"];
export type MethodologyItem = S["MethodologyOut"];
export type MethodologyVersionInfo = S["MethodologyVersionInfo"];
export type MethodologyVersion = S["MethodologyVersionOut"];
export type AiProvider = S["ProviderOut"];
export type AiJobModel = S["JobModelOut"];
export type AiTestResult = S["TestResult"];
export type AiUsageRow = S["UsageRow"];
