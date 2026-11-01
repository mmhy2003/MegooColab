// Package tools installs the Tool Hub's MCP servers and skills at user level for each agent program on this
// machine (one Translator per program), keeps a manifest of what it installed so it only ever updates or
// removes its own entries, notices hand edits (drift) and lists what was set up by hand (a scan for import).
package tools
