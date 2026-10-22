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
export type TaskType = Task["type"];
export type Priority = Task["priority"];
export type ColumnCategory = Column["category"];
export type ActivityItem = S["ActivityItem"];
export type Attachment = S["AttachmentOut"];
export type Sprint = S["SprintOut"];
export type BurndownPoint = S["BurndownPoint"];
export type VelocityPoint = S["VelocityPoint"];
export type AuditEntry = S["AuditOut"];
export type AdminSettings = S["AdminSettingsOut"];
