import { ApiError } from "@/lib/api";

const MESSAGES: Record<string, string> = {
  invalid_credentials: "Wrong email or password.",
  locked: "Too many attempts. Try again in 15 minutes.",
  totp_required: "Enter the code from your authenticator app.",
  invalid_or_expired_token: "This link is invalid or has expired. Ask your admin for a new one.",
  invalid_current_password: "Your current password is wrong.",
  invalid_code: "That code didn't match. Check your authenticator app and try again.",
  invalid_password_or_code: "Wrong password or code.",
  already_set_up: "MegooColab is already set up. Sign in instead.",
  email_taken: "Someone already uses that email.",
  last_admin: "There must always be at least one active admin.",
  cannot_deactivate_self: "You can't deactivate your own account.",
  team_name_taken: "A team with that name already exists.",
  team_has_projects: "Move or delete this team's projects first.",
  project_key_taken: "That project key is already in use.",
  team_not_yours: "You can only use teams you belong to.",
  last_before_or_done_column: "A project needs at least one 'before work' column and one 'done' column.",
  move_to_required: "This column has tasks. Choose where to move them.",
  label_name_taken: "A label with that name already exists.",
  assignee_no_access: "That person isn't on any of this project's teams.",
  invalid_parent: "That parent isn't allowed for this kind of task.",
  active_sprint_exists: "Finish the active sprint before starting another.",
  sprints_disabled: "Sprints are turned off for this project.",
  attachment_too_large: "Attachments can be at most 25 MB.",
  smtp_not_configured: "Set up email (SMTP) first.",
  project_not_found: "Project not found.",
  task_not_found: "Task not found.",
  cannot_use_agent: "You can only use your own agents, or agents on projects you manage.",
  agent_not_bound: "That agent isn't set up for this project. Add the project to the agent first.",
  unknown_agent: "That agent no longer exists.",
  agent_has_active_runs: "This agent is working on a task. Cancel its runs first.",
  agent_name_taken: "You already have an agent with that name.",
  project_not_accessible: "You don't have access to that project.",
  local_path_not_absolute: "Enter the full path to the repository, such as C:\\code\\payments or /home/me/code/payments.",
  task_not_assigned_to_agent: "Assign this task to the agent before starting a run.",
  forbidden: "You don't have permission to do that.",
  validation_error: "Some fields are invalid.",
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    return MESSAGES[err.detail] ?? (err.status >= 500 ? "Something went wrong on the server." : err.detail);
  }
  return "Couldn't reach the server. Check your connection.";
}
